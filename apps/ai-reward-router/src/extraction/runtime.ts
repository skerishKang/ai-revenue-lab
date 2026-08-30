import type {
  CandidateReviewRequest,
  ExtractionInput,
  ExtractionPipelineResult,
  ExtractionRunProvenance,
  OpportunityExtractor,
} from './domain.js';
import {
  classifyConflictRisks,
  normalizeCandidate,
  validateCandidateSemantics,
  validateCandidateStructure,
  validateEvidenceCoverage,
} from './validators.js';

function failedReview(candidateId: string, error: string): CandidateReviewRequest {
  return Object.freeze({
    candidateId,
    state: 'REVIEW_REQUIRED',
    riskCodes: Object.freeze(['MODEL_SCHEMA_FAILURE'] as const),
    structuralErrors: Object.freeze([error]),
    semanticErrors: Object.freeze([]),
    evidenceErrors: Object.freeze([]),
    publicationAllowed: false,
    verificationAllowed: false,
  });
}

export async function runExtractionPipeline(
  extractor: OpportunityExtractor,
  input: ExtractionInput,
): Promise<ExtractionPipelineResult> {
  try {
    const output = await extractor.extract(input);
    const candidate = normalizeCandidate(output.candidate);
    const structuralErrors = [
      ...validateCandidateStructure(candidate),
      ...(candidate.sourceSnapshotId === input.snapshot.id ? [] : ['candidate sourceSnapshotId does not match extraction input']),
      ...(candidate.sourceId === input.snapshot.sourceId ? [] : ['candidate sourceId does not match extraction input']),
    ];
    const semanticErrors = [...validateCandidateSemantics(candidate)];
    const evidenceErrors = [...validateEvidenceCoverage(candidate, output.evidence)];
    const risks = classifyConflictRisks(candidate, output.evidence, structuralErrors, semanticErrors, evidenceErrors);

    const provenance: ExtractionRunProvenance = Object.freeze({
      extractionRunId: input.runId,
      sourceSnapshotId: input.snapshot.id,
      inputSnapshotSha256: input.snapshot.contentHash,
      extractorKind: extractor.kind,
      providerId: extractor.providerId,
      modelId: extractor.modelId,
      promptVersion: extractor.promptVersion,
      schemaVersion: input.schemaVersion,
      startedAt: input.startedAt,
      completedAt: input.startedAt,
      rawStructuredOutputHash: output.rawStructuredOutputHash,
      status: structuralErrors.length > 0 ? 'SCHEMA_REJECTED' : 'SUCCESS',
      validationErrors: Object.freeze([...structuralErrors, ...semanticErrors, ...evidenceErrors]),
      humanCorrectionLineage: null,
    });

    const review: CandidateReviewRequest = Object.freeze({
      candidateId: candidate.candidateId,
      state: 'REVIEW_REQUIRED',
      riskCodes: risks,
      structuralErrors: Object.freeze(structuralErrors),
      semanticErrors: Object.freeze(semanticErrors),
      evidenceErrors: Object.freeze(evidenceErrors),
      publicationAllowed: false,
      verificationAllowed: false,
    });

    return Object.freeze({
      candidate,
      evidence: Object.freeze([...output.evidence]),
      provenance,
      review,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'extractor failed with unknown error';
    const provenance: ExtractionRunProvenance = Object.freeze({
      extractionRunId: input.runId,
      sourceSnapshotId: input.snapshot.id,
      inputSnapshotSha256: input.snapshot.contentHash,
      extractorKind: extractor.kind,
      providerId: extractor.providerId,
      modelId: extractor.modelId,
      promptVersion: extractor.promptVersion,
      schemaVersion: input.schemaVersion,
      startedAt: input.startedAt,
      completedAt: input.startedAt,
      rawStructuredOutputHash: null,
      status: 'FAILED',
      validationErrors: Object.freeze([message]),
      humanCorrectionLineage: null,
    });
    return Object.freeze({
      candidate: null,
      evidence: Object.freeze([]),
      provenance,
      review: failedReview(`${input.runId}:failed`, message),
    });
  }
}
