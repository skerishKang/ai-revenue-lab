"""Offline rehearsal: manifest and copy local objects to a NEW staging directory.

This does not write R2 or apply production restores.
"""
import hashlib
from pathlib import Path

class Refused(RuntimeError): pass

def manifest(root):
    root=Path(root).resolve(strict=True)
    if not root.is_dir(): raise Refused('not_directory')
    out={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise Refused('symlink_refused')
        if not path.is_file(): continue
        relative=path.relative_to(root).as_posix()
        digest=hashlib.sha256();size=0
        with path.open('rb') as stream:
            while chunk:=stream.read(1024*1024):
                digest.update(chunk);size+=len(chunk)
        out[relative]=(size,digest.hexdigest())
    return out

def plan(baseline,current):
    a,b=manifest(baseline),manifest(current)
    return {'added':len(b.keys()-a.keys()),'deleted':len(a.keys()-b.keys()),'changed':sum(a[k]!=b[k] for k in a.keys()&b.keys())}

def stage(current,new_target):
    current=Path(current).resolve(strict=True);target=Path(new_target).resolve()
    if target.exists() or target.is_relative_to(current) or current.is_relative_to(target): raise Refused('target_must_be_new_and_separate')
    before=manifest(current);target.mkdir(parents=True,exist_ok=False)
    for key,(size,digest) in before.items():
        src=current.joinpath(*key.split('/'));dst=target.joinpath(*key.split('/'));dst.parent.mkdir(parents=True,exist_ok=True)
        with src.open('rb') as reader,dst.open('xb') as writer:
            while chunk:=reader.read(1024*1024):writer.write(chunk)
    if manifest(current)!=before or manifest(target)!=before: raise Refused('stage_mismatch')
    return {'objects':len(before),'bytes':sum(x[0] for x in before.values())}
