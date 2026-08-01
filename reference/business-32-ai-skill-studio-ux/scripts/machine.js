/* Business 32 · AI Skill Studio — Phase 2 deterministic synthetic state machine.
 * Pure, side-effect-free reducer. Works in node (module.exports) and browser (window.B32Machine).
 * 24 states: 16 domain + 8 general.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.B32Machine = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const DOMAIN_STATES = [
    'initial',
    'task-selected',
    'input-incomplete',
    'ready',
    'running',
    'step-complete',
    'missing-evidence',
    'conflicting-evidence',
    'stopped',
    'draft-result',
    'review-requested',
    'correction-required',
    'revised',
    'approval-pending',
    'approved',
    'skill-saved'
  ];

  const GENERAL_STATES = [
    'loading',
    'empty',
    'validation-error',
    'system-error',
    'retry',
    'cancelled',
    'resume',
    'completed'
  ];

  const ALL_STATES = DOMAIN_STATES.concat(GENERAL_STATES);

  const HERO_LABELS = [
    'AI-ASSISTED STEP',
    'HUMAN ACTION',
    'SOURCE EVIDENCE',
    'MISSING EVIDENCE',
    'CONFLICTING EVIDENCE',
    'DRAFT RESULT',
    'REVIEW CORRECTION',
    'NOT YET APPROVED',
    'HUMAN-APPROVED',
    'VERIFIED ORGANIZATIONAL AI SKILL'
  ];

  function notSaved() {
    return '브라우저 메모리에만 존재 · 저장되지 않음';
  }

  const ROLES = ['operator', 'reviewer'];

  const ROLE_NAMES = {
    operator: '업무 실행자',
    reviewer: '합성 운영 책임자 · 사람 검토자'
  };

  const REVIEWER_ONLY_ACTIONS = ['approve-review', 'reject-review', 'approve'];

  const SELF_REVIEW_BLOCK_MESSAGE =
    '업무 실행자는 자신의 결과를 검토하거나 승인할 수 없습니다. 합성 운영 책임자에게 인계하십시오.';

  function roleName(role) {
    return ROLE_NAMES[role] || role;
  }

  function isReviewer(ctx) {
    return ctx.activeRole === 'reviewer';
  }

  function recordHandoff(ctx, state, action) {
    ctx.roleHistory.push({
      from: ctx.activeRole === 'reviewer' ? 'reviewer' : 'operator',
      to: ctx.activeRole === 'reviewer' ? 'operator' : 'reviewer',
      action: action,
      state: state
    });
  }

  function rejectRole(state) {
    return {
      to: 'validation-error',
      previous: state,
      feedback: fb({
        failure: SELF_REVIEW_BLOCK_MESSAGE,
        retry: '검토자에게 인계한 뒤 다시 시도합니다.',
        next: '검토자에게 인계합니다.'
      })
    };
  }

  function makeContext(scenario, fixture) {
    const required = (fixture.task.requiredInputs || []).map(function (input) {
      return {
        id: input.id,
        label: input.label,
        confirmed: scenario === 'empty-bench' ? false : !!input.confirmed
      };
    });
    return {
      scenario: scenario,
      bench: scenario === 'empty-bench' ? [] : [fixture.task],
      selectedTaskId: null,
      activeRole: 'operator',
      roleHistory: [],
      inputs: required,
      stepIndex: 0,
      revisionRun: false,
      steps: fixture.steps,
      evidence: {
        verified: [],
        missing: [],
        conflicts: [],
        opened: null
      },
      exceptions: fixture.exceptions.map(function (e) {
        return { id: e.id, label: e.label, text: e.text };
      }),
      supplement: null,
      conflictDecision: null,
      draft: {
        title: fixture.draft.initial.title,
        status: fixture.draft.initial.status,
        text: fixture.draft.initial.rejected,
        note: fixture.draft.initial.rejectedReason
      },
      corrections: [],
      reviewer: { decision: null, note: null },
      skill: null,
      versions: [],
      previous: null,
      error: null,
      cancelledResult: null
    };
  }

  function createMachine(fixture, scenario) {
    const kind = scenario || 'standard';
    return {
      state: 'loading',
      scenario: kind,
      fixture: fixture,
      context: makeContext(kind, fixture)
    };
  }

  function fb(partial) {
    return Object.assign(
      {
        inProgress: null,
        completed: null,
        notSaved: null,
        reviewReason: null,
        failure: null,
        retry: null,
        cancel: null,
        next: null
      },
      partial
    );
  }

  function requiredInputsComplete(ctx) {
    return ctx.inputs.every(function (input) {
      return input.confirmed;
    });
  }

  function missingInputs(ctx) {
    return ctx.inputs
      .filter(function (input) {
        return !input.confirmed;
      })
      .map(function (input) {
        return input.label;
      });
  }

  function stepById(ctx, id) {
    return ctx.steps.find(function (step) {
      return step.id === id;
    });
  }

  function currentStep(ctx) {
    return ctx.steps[ctx.stepIndex];
  }

  function lastStepIndex(ctx) {
    return ctx.steps.length - 1;
  }

  function recordVerified(ctx, step) {
    ctx.evidence.verified.push({ stepId: step.id, result: step.result });
  }

  function MISSING(ctx, fixture) {
    const s = fixture.scenarios.standard.missingEvidence;
    const entry = { supplier: s.supplier, field: s.field, text: s.text };
    ctx.evidence.missing.push(entry);
    ctx.exceptions.push({ id: 'ex-run-missing', label: s.label, text: entry.field + ' 미확인' });
    ctx.error = s.text;
    return entry;
  }

  function CONFLICT(ctx, fixture) {
    const s = fixture.scenarios.standard.conflict;
    ctx.evidence.conflicts.push({ text: s.text, resolution: s.resolution });
    ctx.exceptions.push({ id: 'ex-run-conflict', label: s.label, text: '납기·총액 충돌: 최저가 자동 판정 금지' });
    ctx.error = s.text;
    return s;
  }

  const RULES = {
    loading: {
      'load-ok': function (ctx) {
        if (ctx.bench.length === 0) {
          return { to: 'empty', feedback: fb({ completed: '업무대가 비어 있습니다.', next: '업무대에 합성 업무를 불러옵니다.' }) };
        }
        return { to: 'initial', feedback: fb({ completed: '업무 실습대가 준비되었습니다.', next: '실행할 합성 업무를 선택합니다.' }) };
      },
      'load-error': function (ctx) {
        return {
          to: 'system-error',
          previous: 'loading',
          feedback: fb({ failure: '합성 업무대를 불러오지 못했습니다.', retry: '재시도를 누르면 같은 상태에서 다시 시도합니다.', next: '재시도를 실행합니다.' })
        };
      }
    },
    empty: {
      'load-tasks': function () {
        return { to: 'initial', feedback: fb({ completed: '합성 업무대가 채워졌습니다.', next: '실행할 합성 업무를 선택합니다.' }) };
      }
    },
    initial: {
      'select-task': function (ctx, payload) {
        ctx.selectedTaskId = (payload && payload.taskId) || 'b32-001';
        return {
          to: 'task-selected',
          feedback: fb({ completed: '업무가 선택되었습니다.', next: '업무 범위와 금지사항을 확인합니다.' })
        };
      }
    },
    'task-selected': {
      'list-tasks': function () {
        return { to: 'initial', feedback: fb({ completed: '업무 실습대로 돌아갔습니다.', next: '다른 합성 업무를 선택할 수 있습니다.' }) };
      },
      'check-inputs': function (ctx) {
        if (requiredInputsComplete(ctx)) {
          return { to: 'ready', feedback: fb({ completed: '필수 입력자료가 모두 확인되었습니다.', next: '단계별 실행을 시작합니다.' }) };
        }
        return {
          to: 'input-incomplete',
          feedback: fb({
            completed: '필수 입력자료가 부족합니다.',
            failure: '확인되지 않은 입력자료: ' + missingInputs(ctx).join(', '),
            next: '누락 입력자료를 확인하고 보완합니다.'
          })
        };
      }
    },
    'input-incomplete': {
      'check-inputs': function (ctx) {
        if (requiredInputsComplete(ctx)) {
          return { to: 'ready', feedback: fb({ completed: '필수 입력자료가 모두 확인되었습니다.', next: '단계별 실행을 시작합니다.' }) };
        }
        return {
          to: 'input-incomplete',
          feedback: fb({
            completed: '아직 미확인 항목이 있습니다.',
            failure: '미확인: ' + missingInputs(ctx).join(', '),
            next: '보완할 입력자료를 선택합니다.'
          })
        };
      },
      'supplement': function (ctx, payload) {
        const target = payload && payload.inputId;
        const confirmedList = ctx.inputs.filter(function (i) {
          return i.confirmed;
        });
        const remaining = ctx.inputs.filter(function (i) {
          return !i.confirmed;
        });
        if (!target || !remaining.some(function (i) {
          return i.id === target;
        })) {
          return {
            to: 'validation-error',
            previous: 'input-incomplete',
            feedback: fb({
              failure: '보완할 입력자료를 선택하지 않았거나 이미 확인된 항목입니다.',
              retry: '보완할 항목을 선택한 뒤 다시 확인합니다.',
              next: '확인 항목을 다시 제출합니다.'
            })
          };
        }
        remaining.forEach(function (i) {
          if (i.id === target) i.confirmed = true;
        });
        if (requiredInputsComplete(ctx)) {
          return {
            to: 'ready',
            feedback: fb({ completed: '필수 입력자료가 모두 확인되었습니다.', notSaved: notSaved(), next: '단계별 실행을 시작합니다.' })
          };
        }
        return {
          to: 'input-incomplete',
          feedback: fb({
            completed: '한 항목이 보완되었습니다.',
            failure: '아직 미확인: ' + missingInputs(ctx).join(', '),
            notSaved: notSaved(),
            next: '남은 입력자료를 확인합니다.'
          })
        };
      }
    },
    ready: {
      'begin-run': function (ctx) {
        ctx.stepIndex = 0;
        ctx.revisionRun = false;
        return { to: 'running', feedback: fb({ completed: '실행을 시작했습니다.', next: currentStep(ctx).title + ' 단계를 수행합니다.' }) };
      }
    },
    running: {
      'complete-step': function (ctx, payload, fixture) {
        const step = currentStep(ctx);
        const scen = fixture.scenarios.standard;
        const supplementResolves = ctx.revisionRun || (ctx.supplement && ctx.supplement.resolved);
        if (!ctx.revisionRun && step.id === scen.missingStep && !supplementResolves) {
          MISSING(ctx, fixture);
          return {
            to: 'missing-evidence',
            feedback: fb({
              failure: scen.missingEvidence.text,
              reviewReason: '누락 증거를 자동 추정할 수 없습니다.',
              next: '공급업체에 보완을 요청하거나 실행을 중단합니다.'
            })
          };
        }
        if (!ctx.revisionRun && step.id === scen.conflictStep) {
          CONFLICT(ctx, fixture);
          return {
            to: 'conflicting-evidence',
            feedback: fb({
              failure: scen.conflict.text,
              reviewReason: '최저가를 자동 최선으로 판정할 수 없습니다.',
              next: '사람이 충돌을 판단하거나 실행을 중단합니다.'
            })
          };
        }
        recordVerified(ctx, step);
        if (ctx.stepIndex === lastStepIndex(ctx)) {
          return {
            to: 'draft-result',
            feedback: fb({
              completed: '모든 단계가 완료되어 초안이 만들어졌습니다.',
              notSaved: notSaved(),
              reviewReason: '초안은 검토 전에는 확정으로 간주하지 않습니다.',
              next: '추천 메모 초안을 확인하고 사람 검토를 요청합니다.'
            })
          };
        }
        return {
          to: 'step-complete',
          feedback: fb({
            completed: step.title + ' 단계가 완료되었습니다.',
            notSaved: notSaved(),
            next: '다음 단계로 진행합니다.'
          })
        };
      },
      'stop-run': function (ctx) {
        ctx.cancelledResult = '실행을 중단했습니다. 진행 상황은 유지됩니다.';
        return { to: 'stopped', feedback: fb({ completed: ctx.cancelledResult, next: '재개하거나 취소합니다.' }) };
      }
    },
    'step-complete': {
      'next-step': function (ctx, payload, fixture) {
        if (ctx.stepIndex >= lastStepIndex(ctx)) {
          return { to: 'draft-result', feedback: fb({ completed: '모든 단계가 완료되어 초안이 만들어졌습니다.', next: '초안을 확인합니다.' }) };
        }
        ctx.stepIndex += 1;
        return { to: 'running', feedback: fb({ completed: '다음 단계로 진행합니다.', next: currentStep(ctx).title + ' 단계를 수행합니다.' }) };
      },
      'stop-run': function (ctx) {
        ctx.cancelledResult = '실행을 중단했습니다. 진행 상황은 유지됩니다.';
        return { to: 'stopped', feedback: fb({ completed: ctx.cancelledResult, next: '재개하거나 취소합니다.' }) };
      }
    },
    'missing-evidence': {
      'request-supplement': function (ctx, payload, fixture) {
        const note = (payload && payload.note) || fixture.scenarios.standard.supplement.note;
        ctx.supplement = { note: note, resolved: false };
        return {
          to: 'stopped',
          feedback: fb({
            completed: '보완 요청을 기록했습니다.',
            notSaved: notSaved(),
            next: '보완 접수 후 실행을 재개합니다.'
          })
        };
      },
      'stop-run': function (ctx) {
        ctx.cancelledResult = '누락 증거 상태에서 실행을 중단했습니다.';
        return { to: 'stopped', feedback: fb({ completed: ctx.cancelledResult, next: '재개하거나 취소합니다.' }) };
      }
    },
    'conflicting-evidence': {
      'resolve-conflict': function (ctx, payload, fixture) {
        const decision = payload && payload.decision;
        if (!decision) {
          return {
            to: 'validation-error',
            previous: 'conflicting-evidence',
            feedback: fb({
              failure: '충돌 판단(후보와 이유)을 선택해야 합니다.',
              retry: '후보와 근거를 선택한 뒤 다시 제출합니다.',
              next: '사람 판단을 다시 제출합니다.'
            })
          };
        }
        ctx.conflictDecision = {
          candidate: decision,
          reason: (payload && payload.reason) || fixture.scenarios.standard.conflictDecision.reason
        };
        recordVerified(ctx, currentStep(ctx));
        return {
          to: 'step-complete',
          feedback: fb({
            completed: '사람이 충돌을 판단했습니다.',
            notSaved: notSaved(),
            next: '다음 단계로 진행합니다.'
          })
        };
      },
      'stop-run': function (ctx) {
        ctx.cancelledResult = '충돌 증거 상태에서 실행을 중단했습니다.';
        return { to: 'stopped', feedback: fb({ completed: ctx.cancelledResult, next: '재개하거나 취소합니다.' }) };
      }
    },
    stopped: {
      'resume-run': function (ctx) {
        return { to: 'resume', feedback: fb({ completed: '재개 확인 화면입니다.', next: '재개를 확인하면 중단 지점부터 이어집니다.' }) };
      },
      'cancel': function (ctx) {
        return {
          to: 'cancelled',
          feedback: fb({ completed: ctx.cancelledResult || '실행을 취소했습니다.', cancel: '진행 기록은 버리지 않으며 업무 선택으로 돌아갑니다.', next: '업무를 다시 선택합니다.' })
        };
      }
    },
    resume: {
      'resume-confirm': function (ctx) {
        if (ctx.supplement && !ctx.supplement.resolved) {
          ctx.supplement.resolved = true;
        }
        return { to: 'running', feedback: fb({ completed: '중단 지점부터 재개했습니다.', next: currentStep(ctx).title + ' 단계를 다시 수행합니다.' }) };
      }
    },
    cancelled: {
      'select-task': function (ctx, payload) {
        ctx.selectedTaskId = (payload && payload.taskId) || 'b32-001';
        return { to: 'task-selected', feedback: fb({ completed: '업무를 다시 선택했습니다.', next: '범위와 금지사항을 확인합니다.' }) };
      },
      'list-tasks': function () {
        return { to: 'initial', feedback: fb({ completed: '업무 실습대로 돌아갔습니다.', next: '실행할 합성 업무를 선택합니다.' }) };
      }
    },
    'draft-result': {
      'request-review': function (ctx) {
        return {
          to: 'review-requested',
          feedback: fb({
            completed: '사람 검토를 요청했습니다.',
            notSaved: notSaved(),
            reviewReason: '초안은 DRAFT RESULT로 확정이 아니며 검토가 필요합니다.',
            next: '검토자에게 인계합니다.'
          })
        };
      },
      'handoff-to-reviewer': function (ctx, payload, fixture, state) {
        if (isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'draft-result',
            feedback: fb({
              failure: '이미 검토자 역할입니다. 인계가 필요하지 않습니다.',
              retry: '검토자 역할로 계속 진행합니다.',
              next: '검토를 진행합니다.'
            })
          };
        }
        ctx.activeRole = 'reviewer';
        recordHandoff(ctx, state, 'handoff-to-reviewer');
        return {
          to: 'draft-result',
          feedback: fb({
            completed: '검토자에게 인계했습니다.',
            next: '초안을 검토하고 수정 요청 또는 승인 의사를 결정합니다.'
          })
        };
      },
      'handoff-to-operator': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'draft-result',
            feedback: fb({
              failure: '실행자 역할입니다. 반환이 필요하지 않습니다.',
              retry: '실행자 역할로 계속 진행합니다.',
              next: '검토 요청을 진행합니다.'
            })
          };
        }
        ctx.activeRole = 'operator';
        recordHandoff(ctx, state, 'handoff-to-operator');
        return {
          to: 'draft-result',
          feedback: fb({
            completed: '초안을 실행자에게 반환했습니다.',
            next: '실행자 역할로 이어서 진행합니다.'
          })
        };
      }
    },
    'review-requested': {
      'handoff-to-reviewer': function (ctx, payload, fixture, state) {
        if (isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'review-requested',
            feedback: fb({
              failure: '이미 검토자 역할입니다.',
              retry: '검토자 역할로 계속 진행합니다.',
              next: '검토를 진행합니다.'
            })
          };
        }
        ctx.activeRole = 'reviewer';
        recordHandoff(ctx, state, 'handoff-to-reviewer');
        return {
          to: 'review-requested',
          feedback: fb({
            completed: '검토자에게 인계했습니다.',
            next: '검토 승인 또는 수정 요청을 결정합니다.'
          })
        };
      },
      'handoff-to-operator': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'review-requested',
            feedback: fb({
              failure: '실행자에게 반환할 수 있는 상태가 아닙니다.',
              retry: '검토자 역할에서 반환합니다.',
              next: '검토를 진행합니다.'
            })
          };
        }
        ctx.activeRole = 'operator';
        recordHandoff(ctx, state, 'handoff-to-operator');
        return {
          to: 'review-requested',
          feedback: fb({
            completed: '실행자에게 반환했습니다.',
            next: '실행자 역할로 이어서 진행합니다.'
          })
        };
      },
      'reject-review': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) return rejectRole(state);
        const note = (payload && payload.note) || '약한 추천을 근거가 있는 판단으로 수정해야 함';
        ctx.reviewer = { decision: 'rejected', note: note };
        ctx.draft.note = note;
        return {
          to: 'correction-required',
          feedback: fb({
            completed: '검토자가 수정 요청을 보냈습니다.',
            reviewReason: note,
            next: '수정 사항을 실행자에게 반환합니다.'
          })
        };
      },
      'approve-review': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) return rejectRole(state);
        return { to: 'approval-pending', feedback: fb({ completed: '검토자가 승인 의사를 밝혔습니다.', next: '사람 최종 승인을 확인합니다.' }) };
      }
    },
    'correction-required': {
      'handoff-to-operator': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'correction-required',
            feedback: fb({
              failure: '검토자 역할에서만 실행자에게 반환할 수 있습니다.',
              retry: '검토자 역할에서 반환합니다.',
              next: '수정 요청을 실행자에게 반환합니다.'
            })
          };
        }
        ctx.activeRole = 'operator';
        recordHandoff(ctx, state, 'handoff-to-operator');
        return {
          to: 'correction-required',
          feedback: fb({
            completed: '수정 요청을 실행자에게 반환했습니다.',
            next: '수정 사항을 초안에 반영합니다.'
          })
        };
      },
      'apply-correction': function (ctx, payload, fixture) {
        ctx.corrections.push({ text: fixture.draft.initial.corrected, note: fixture.draft.initial.correctedReason });
        ctx.draft.text = fixture.draft.initial.corrected;
        ctx.draft.note = fixture.draft.initial.correctedReason;
        return {
          to: 'revised',
          feedback: fb({
            completed: '수정 사항을 초안에 반영했습니다.',
            notSaved: notSaved(),
            next: '수정된 절차를 재실행하거나 다시 검토를 요청합니다.'
          })
        };
      }
    },
    revised: {
      'handoff-to-reviewer': function (ctx, payload, fixture, state) {
        if (isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'revised',
            feedback: fb({
              failure: '이미 검토자 역할입니다.',
              retry: '검토자 역할로 계속 진행합니다.',
              next: '검토를 진행합니다.'
            })
          };
        }
        ctx.activeRole = 'reviewer';
        recordHandoff(ctx, state, 'handoff-to-reviewer');
        return {
          to: 'review-requested',
          feedback: fb({
            completed: '수정된 초안을 검토자에게 인계했습니다.',
            next: '검토 승인 또는 수정 요청을 결정합니다.'
          })
        };
      },
      're-run': function (ctx) {
        ctx.stepIndex = 0;
        ctx.revisionRun = true;
        return {
          to: 'running',
          feedback: fb({
            completed: '수정된 절차를 재실행합니다.',
            notSaved: notSaved(),
            next: '재실행 단계를 순서대로 수행합니다.'
          })
        };
      },
      'request-review': function () {
        return {
          to: 'review-requested',
          feedback: fb({
            completed: '수정된 초안으로 사람 검토를 다시 요청했습니다.',
            notSaved: notSaved(),
            next: '합성 운영 책임자에게 인계합니다.'
          })
        };
      },
      'handoff-to-operator': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'revised',
            feedback: fb({
              failure: '실행자 역할입니다. 반환이 필요하지 않습니다.',
              retry: '실행자 역할로 계속 진행합니다.',
              next: '수정된 절차를 재실행합니다.'
            })
          };
        }
        ctx.activeRole = 'operator';
        recordHandoff(ctx, state, 'handoff-to-operator');
        return {
          to: 'revised',
          feedback: fb({
            completed: '수정된 절차를 실행자에게 반환했습니다.',
            next: '수정된 절차를 재실행합니다.'
          })
        };
      }
    },
    'approval-pending': {
      'handoff-to-reviewer': function (ctx, payload, fixture, state) {
        if (isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'approval-pending',
            feedback: fb({
              failure: '이미 검토자 역할입니다.',
              retry: '검토자 역할로 계속 진행합니다.',
              next: '사람 최종 승인을 진행합니다.'
            })
          };
        }
        ctx.activeRole = 'reviewer';
        recordHandoff(ctx, state, 'handoff-to-reviewer');
        return {
          to: 'approval-pending',
          feedback: fb({
            completed: '승인 단계를 검토자에게 인계했습니다.',
            next: '검토자가 사람 최종 승인을 확인합니다.'
          })
        };
      },
      'handoff-to-operator': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'approval-pending',
            feedback: fb({
              failure: '검토자 역할에서만 실행자에게 반환할 수 있습니다.',
              retry: '검토자 역할에서 반환합니다.',
              next: '사람 최종 승인을 진행합니다.'
            })
          };
        }
        ctx.activeRole = 'operator';
        recordHandoff(ctx, state, 'handoff-to-operator');
        return {
          to: 'approval-pending',
          feedback: fb({
            completed: '승인 단계를 실행자에게 반환했습니다.',
            next: '승인 완료 후 스킬을 저장할 수 있습니다.'
          })
        };
      },
      'approve': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) return rejectRole(state);
        return {
          to: 'approved',
          feedback: fb({
            completed: '사람이 최종 승인했습니다.',
            reviewReason: '승인 전 초안은 NOT YET APPROVED였습니다.',
            next: '재사용 가능한 스킬 카드를 생성합니다.'
          })
        };
      },
      'save-skill': function () {
        return {
          to: 'validation-error',
          previous: 'approval-pending',
          feedback: fb({
            failure: '사람 승인 전에는 스킬을 저장할 수 없습니다.',
            retry: '사람 최종 승인을 먼저 확인한 뒤 다시 저장합니다.',
            next: '사람 최종 승인을 진행합니다.'
          })
        };
      }
    },
    approved: {
      'handoff-to-operator': function (ctx, payload, fixture, state) {
        if (!isReviewer(ctx)) {
          return {
            to: 'validation-error',
            previous: 'approved',
            feedback: fb({
              failure: '이미 실행자 역할입니다.',
              retry: '실행자 역할로 스킬을 저장합니다.',
              next: '스킬 카드를 저장합니다.'
            })
          };
        }
        ctx.activeRole = 'operator';
        recordHandoff(ctx, state, 'handoff-to-operator');
        return {
          to: 'approved',
          feedback: fb({
            completed: '승인된 결과를 실행자에게 반환했습니다.',
            next: '승인된 스킬 카드를 저장합니다.'
          })
        };
      },
      'save-skill': function (ctx, payload, fixture) {
        const skill = {
          name: fixture.skill.name,
          version: fixture.skill.version,
          owner: fixture.skill.owner,
          reviewDate: fixture.skill.reviewDate,
          nextReview: fixture.skill.nextReview,
          allowedUse: fixture.skill.allowedUse,
          prohibitedUse: fixture.skill.prohibitedUse,
          authority: fixture.skill.authority,
          exceptions: ctx.exceptions.map(function (e) {
            return { id: e.id, label: e.label, text: e.text };
          }),
          evidenceMissing: ctx.evidence.missing.map(function (m) {
            return m.field;
          }),
          evidenceConflicts: ctx.evidence.conflicts.map(function (c) {
            return c.text;
          }),
          supplement: ctx.supplement,
          conflictDecision: ctx.conflictDecision,
          corrections: ctx.corrections.map(function (c) {
            return { text: c.text, note: c.note };
          })
        };
        ctx.skill = skill;
        ctx.versions.push({ version: skill.version, savedAt: '2026-08-01', owner: skill.owner });
        return {
          to: 'skill-saved',
          feedback: fb({
            completed: '스킬 카드를 저장했습니다.',
            next: '버전·담당자·다음 검토일을 확인합니다.'
          })
        };
      }
    },
    'skill-saved': {
      'complete': function () {
        return {
          to: 'completed',
          feedback: fb({ completed: '전체 journey가 완료되었습니다.', next: '버전 이력을 확인하거나 새 업무를 시작합니다.' })
        };
      },
      'list-tasks': function (ctx) {
        ctx.skill = null;
        ctx.versions = [];
        return { to: 'initial', feedback: fb({ completed: '새 업무를 위해 실습대로 돌아갔습니다.', next: '실행할 합성 업무를 선택합니다.' }) };
      }
    },
    completed: {
      'list-tasks': function (ctx) {
        ctx.skill = null;
        ctx.versions = [];
        return { to: 'initial', feedback: fb({ completed: '새 업무를 시작합니다.', next: '실행할 합성 업무를 선택합니다.' }) };
      }
    },
    'system-error': {
      'retry': function () {
        return { to: 'retry', feedback: fb({ completed: '재시도를 준비했습니다.', next: '재시도를 확인합니다.' }) };
      }
    },
    retry: {
      'retry-confirm': function (ctx) {
        const back = ctx.previous || 'loading';
        return { to: back, feedback: fb({ completed: '같은 상태에서 다시 시도합니다.', next: '이전 행동을 다시 실행합니다.' }) };
      }
    },
    'validation-error': {
      'ack': function (ctx) {
        const back = ctx.previous || 'input-incomplete';
        return { to: back, feedback: fb({ completed: '오류를 확인하고 이전 상태로 돌아갑니다.', next: '이전 행동을 다시 시도합니다.' }) };
      }
    }
  };

  function transition(machine, action, payload) {
    if (!machine || !machine.state) throw new Error('B32Machine: invalid machine');
    const table = RULES[machine.state];
    if (!table || !table[action]) {
      throw new Error(
        'B32Machine: invalid transition ' + machine.state + ' + ' + action + ' (forbidden)'
      );
    }
    const result = table[action](machine.context, payload || {}, machine.fixture, machine.state);
    const next = {
      state: result.to,
      scenario: machine.scenario,
      context: machine.context,
      feedback: result.feedback || fb({}),
      previous: result.previous || null,
      fixture: machine.fixture
    };
    if (result.to === 'system-error' || result.to === 'validation-error' || result.to === 'retry') {
      if (result.previous) next.context.previous = result.previous;
    }
    if (next.context && typeof next.context.previous === 'undefined') {
      next.context.previous = null;
    }
    return next;
  }

  function actionAllowed(machine, action) {
    const table = RULES[machine.state];
    if (!table || !table[action]) return false;
    if (REVIEWER_ONLY_ACTIONS.indexOf(action) !== -1) {
      return machine.context.activeRole === 'reviewer';
    }
    return true;
  }

  function canTransition(machine, action) {
    return actionAllowed(machine, action);
  }

  function availableActions(machine) {
    const table = RULES[machine.state] || {};
    return Object.keys(table).filter(function (action) {
      return actionAllowed(machine, action);
    });
  }

  return {
    DOMAIN_STATES: DOMAIN_STATES,
    GENERAL_STATES: GENERAL_STATES,
    ALL_STATES: ALL_STATES,
    HERO_LABELS: HERO_LABELS,
    ROLES: ROLES,
    ROLE_NAMES: ROLE_NAMES,
    roleName: roleName,
    REVIEWER_ONLY_ACTIONS: REVIEWER_ONLY_ACTIONS,
    createMachine: createMachine,
    transition: transition,
    canTransition: canTransition,
    actionAllowed: actionAllowed,
    availableActions: availableActions,
    missingInputs: missingInputs,
    currentStep: currentStep
  };
});
