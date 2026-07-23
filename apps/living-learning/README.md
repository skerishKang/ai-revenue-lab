# Living Learning

Recurring 10-minute learning sessions for Korean adult AI/Python beginners.

## Product

- 10-minute learning sessions with comprehension response and explicit feedback
- Two-phase lessons: first lesson → feedback → adapted second lesson
- Initial curriculum: variables, values, simple conditionals, small Python examples

## Architecture

- FastAPI + SQLite
- Provider-neutral AIProvider protocol with MockProvider for testing
- Versioned migrations (SQLite)
- Atomic transactions for lesson/content/exercise/mastery/feedback state

## Running

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Testing

```bash
pytest tests/ -v
```

## API

- `POST /api/v1/learners` - Create learner and session
- `POST /api/v1/lessons` - Start first lesson
- `POST /api/v1/comprehension` - Record comprehension response
- `POST /api/v1/feedback` - Submit feedback
- `POST /api/v1/lessons/second` - Generate adapted second lesson
- `POST /api/v1/lessons/close` - Finalize lesson
- `GET /health` - Health check with provider info