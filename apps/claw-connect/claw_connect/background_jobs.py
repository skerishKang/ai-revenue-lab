"""Persistent background receipts for the existing Windows command authority.

Inspired by Hermes Agent background process management (MIT, Nous Research).
This module is deliberately not wired to the resident, queue or engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
import codecs
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

from kagent.windows_local_executor import (
    TrustedWindowsExecutionGrant, WindowsSubprocessLocalAgentRuntime,
    _bounded_environment, _require_request_not_future,
)
from kagent.windows_job_object import launch_job_bound_process

_JOB = re.compile(r'job_[0-9a-f]{32}\Z')

class BackgroundJobs:
    """One manager per connector. Stale running jobs are marked failed on restart.

    The existing native Job Object kills child trees when the connector exits;
    completed receipts and output remain available without replaying commands.
    """
    def __init__(self, directory, *, runtime, max_concurrent=2, max_seconds=300):
        if not isinstance(runtime, WindowsSubprocessLocalAgentRuntime):
            raise TypeError('an existing Windows execution runtime is required')
        if type(max_concurrent) is not int or max_concurrent < 1:
            raise ValueError('max_concurrent must be positive')
        if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not 0 < max_seconds < float('inf'):
            raise ValueError('max_seconds must be positive and finite')
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime = runtime
        self.max_concurrent = max_concurrent
        self.max_seconds = max_seconds
        self.lock = threading.RLock()
        self.active = {}
        for path in self.root.glob('job_*.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if _JOB.fullmatch(path.stem) and record.get('state') == 'running':
                    record.update(state='failed', exit_code=None, finished_at=time.time())
                    self._save(record)
            except (OSError, ValueError, TypeError):
                continue

    def _path(self, job_id, suffix):
        if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
            raise KeyError('unknown job')
        return self.root / (job_id + suffix)

    def _load(self, job_id):
        try:
            record = json.loads(self._path(job_id, '.json').read_text(encoding='utf-8'))
            if record.get('job_id') != job_id:
                raise KeyError('unknown job')
            return record
        except (OSError, ValueError, TypeError):
            raise KeyError('unknown job') from None

    def _save(self, record):
        path = self._path(record['job_id'], '.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)

    def start(self, command_spec, *, job_owner):
        if not isinstance(job_owner, str) or not job_owner.strip():
            raise ValueError('job_owner is required')
        now = datetime.now(timezone.utc)
        _require_request_not_future(command_spec, now=now)
        profile, cwd = self.runtime._validate_request(command_spec)
        grant = self.runtime._authorization.authorize(request=command_spec, profile=profile, now=now)
        if not isinstance(grant, TrustedWindowsExecutionGrant):
            raise ValueError('invalid execution grant')
        grant.validate(request=command_spec, profile=profile, now=now)
        with self.lock:
            if len(self.active) >= self.max_concurrent:
                raise RuntimeError('background job limit reached')
            if any(self._load(active_id).get('request_id') == command_spec.request_id for active_id in self.active):
                raise RuntimeError('command request is already active')
            job_id = 'job_' + uuid.uuid4().hex
            start_time = time.time()
            record = {'job_id':job_id, 'owner':job_owner, 'state':'running',
                      'request_id':command_spec.request_id,
                      'started_at':start_time, 'finished_at':None, 'exit_code':None}
            self._path(job_id, '.log').touch(exist_ok=False)
            self._save(record)
            bound = None
            try:
                bound = launch_job_bound_process(list(command_spec.argv), cwd=cwd,
                    environment=_bounded_environment(), creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.active[job_id] = bound
                watcher = threading.Thread(target=self._watch, args=(job_id, bound, min(self.max_seconds, command_spec.timeout_seconds)), daemon=True)
                watcher.start()
            except BaseException:
                if bound is not None:
                    bound.job.terminate_tree()
                    bound.job.close()
                self.active.pop(job_id, None)
                record.update(state='failed', finished_at=time.time())
                self._save(record)
                raise
            return {'job_id':job_id, 'started_at':datetime.fromtimestamp(start_time, timezone.utc).isoformat()}

    def _drain(self, stream, log, output_lock, errors):
        decoder = codecs.getincrementaldecoder(stream.encoding or 'utf-8')(errors='replace')
        try:
            while True:
                chunk = stream.buffer.read1(8192)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                with output_lock:
                    log.write(text.encode('utf-8'))
            tail = decoder.decode(b'', final=True)
            if tail:
                with output_lock:
                    log.write(tail.encode('utf-8'))
        except Exception:
            errors.append(True)
        finally:
            stream.close()

    def _watch(self, job_id, bound, timeout):
        process, job = bound.process, bound.job
        started = []
        errors = []
        timed_out = False
        try:
            with self._path(job_id, '.log').open('ab', buffering=0) as log:
                output_lock = threading.Lock()
                for stream in (process.stdout, process.stderr):
                    if stream is None:
                        raise RuntimeError('missing output stream')
                    thread = threading.Thread(target=self._drain, args=(stream,log,output_lock,errors), daemon=True)
                    thread.start()
                    started.append(thread)
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    job.terminate_tree()
                    process.wait(timeout=5)
                job.terminate_tree()
                if not job.wait_for_empty(timeout_seconds=5):
                    raise RuntimeError('process tree did not exit')
                for thread in started:
                    thread.join(timeout=5)
                if any(thread.is_alive() for thread in started) or errors:
                    raise RuntimeError('output drain failed')
        except Exception:
            try:
                job.terminate_tree()
                process.wait(timeout=5)
            except Exception:
                pass
            failure = True
        else:
            failure = False
        finally:
            job.close()
            with self.lock:
                record = self._load(job_id)
                if record['state'] == 'running':
                    record['state'] = 'killed' if timed_out else ('failed' if failure or process.returncode != 0 else 'done')
                record['exit_code'] = process.returncode
                record['finished_at'] = time.time()
                self._save(record)
                self.active.pop(job_id, None)

    def status(self, job_id):
        with self.lock:
            record = self._load(job_id)
            end = record['finished_at'] or time.time()
            return {'state':record['state'], 'exit_code':record['exit_code'],
                    'elapsed':max(0, end-record['started_at']),
                    'output_size':self._path(job_id,'.log').stat().st_size}

    def output(self, job_id, offset, length):
        if type(offset) is not int or type(length) is not int or offset < 0 or length < 0:
            raise ValueError('offset and length must be non-negative integers')
        with self.lock:
            self._load(job_id)
            with self._path(job_id,'.log').open('rb') as source:
                source.seek(offset)
                return source.read(length).decode('utf-8', errors='replace')

    def kill(self, job_id):
        with self.lock:
            record = self._load(job_id)
            bound = self.active.get(job_id)
            if record['state'] != 'running' or bound is None or bound.process.poll() is not None:
                return False
            if not bound.job.terminate_tree():
                return False
            record['state'] = 'killed'
            self._save(record)
            return True

    def list(self, job_owner):
        with self.lock:
            results = []
            for path in self.root.glob('job_*.json'):
                try:
                    record = self._load(path.stem)
                    if record['owner'] == job_owner:
                        results.append({'job_id':record['job_id'], 'started_at':datetime.fromtimestamp(record['started_at'],timezone.utc).isoformat(), **self.status(record['job_id'])})
                except (KeyError, OSError, ValueError, TypeError):
                    continue
            return sorted(results, key=lambda row: row['started_at'])
