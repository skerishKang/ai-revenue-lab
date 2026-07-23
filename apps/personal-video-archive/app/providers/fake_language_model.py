"""Deterministic fake language-model provider.

Returns validated, structured proposals for the supported LLM workflows.
No network calls are made.  The same input always produces the same output.
"""

from __future__ import annotations

import hashlib
import re

from app.domain.enums import (
    DefaultSort,
    DurationPreference,
    ShortsPreference,
)
from app.domain.models import (
    QueryRuleProposal,
    RecordStructureProposal,
    RuleChangeProposal,
    VideoClassification,
    validate_tags,
)
from app.providers import LanguageModelProvider
from app.providers.fake_video_discovery import _deterministic_seed


# Keyword dictionaries for intent parsing — deterministic, no real model.
_RELATED_TERM_MAP = {
    "chatgpt": ["openai", "gpt", "llm", "ai"],
    "openai": ["chatgpt", "gpt", "llm", "ai"],
    "llm": ["ai", "machine learning", "gpt", "language model"],
    "ai": ["machine learning", "llm", "gpt", "artificial intelligence"],
    "local llm": ["ollama", "llama", "gemma", "qwen"],
    "python": ["programming", "tutorial", "code", "developer"],
    "rust": ["programming", "systems", "performance", "developer"],
    "golang": ["go", "programming", "backend", "developer"],
    "svelte": ["javascript", "frontend", "web", "framework"],
    "react": ["javascript", "frontend", "web", "framework"],
    "next.js": ["react", "javascript", "frontend", "web"],
    "docker": ["container", "devops", "kubernetes", "deployment"],
    "kubernetes": ["docker", "devops", "container", "orchestration"],
    "postgres": ["database", "sql", "postgresql", "backend"],
    "redis": ["cache", "database", "in-memory", "backend"],
}

_EXCLUDED_TERM_MAP = {
    "shorts": ["shorts", "short", "tiktok", "reels"],
    "reaction": ["reaction", "react", "response"],
    "ad": ["ad", "advertisement", "sponsored", "promo"],
    "tutorial": ["beginner", "basics", "fundamentals"],
}

_LANGUAGE_MAP = {
    "korean": ["ko"],
    "english": ["en"],
    "ko": ["ko"],
    "en": ["en"],
    "bilingual": ["en", "ko"],
    "multilingual": ["en", "ko", "ja", "zh"],
}


class FakeLanguageModelProvider(LanguageModelProvider):
    """Deterministic fake LLM provider.

    All methods parse the input text using rule-based heuristics and
    return validated structured proposals.  No network calls.
    """

    def __init__(self, model: str = "fake-pva-v1"):
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def propose_query_rules(self, intent: str) -> QueryRuleProposal:
        """Convert natural-language intent into a search-rule draft."""
        text = intent.lower().strip()

        # Extract primary query: first noun phrase or key topic
        primary = self._extract_primary_query(text, intent)

        # Extract related queries
        related = self._extract_related_queries(text, primary)

        # Extract excluded terms
        excluded = self._extract_excluded_terms(text)

        # Extract required terms
        required = self._extract_required_terms(text, primary)

        # Extract language preferences
        languages = self._extract_languages(text)

        # Extract shorts preference
        shorts = ShortsPreference.INCLUDE
        if "short" in text or "shorts" in text:
            shorts = ShortsPreference.EXCLUDE

        # Extract duration preference
        duration = DurationPreference.ANY
        if "long" in text or "deep dive" in text or "detailed" in text:
            duration = DurationPreference.LONG
        elif "short" in text and "shorts" not in text:
            duration = DurationPreference.SHORT

        # Default sort is always newest
        default_sort = DefaultSort.NEWEST

        rationale = (
            f"Derived from intent: '{intent[:200]}'. "
            f"Primary query '{primary}' with {len(related)} related terms "
            f"and {len(excluded)} excluded terms. "
            f"Shorts {'excluded' if shorts == ShortsPreference.EXCLUDE else 'included'}. "
            f"Default sort: newest first."
        )

        return QueryRuleProposal(
            primary_query=primary,
            related_queries=related,
            required_terms=required,
            excluded_terms=excluded,
            preferred_languages=languages,
            duration_preference=duration,
            shorts_preference=shorts,
            default_sort=default_sort,
            rationale=rationale,
        )

    def _extract_primary_query(self, text: str, original: str) -> str:
        """Extract the primary search query from the intent."""
        # Look for patterns like "about X" or "X updates"
        for pattern in [
            r"about\s+(.+?)(?:\.|,|$)",
            r"(?:following|tracking|watching)\s+(.+?)(?:\.|,|$)",
            r"videos?\s+about\s+(.+?)(?:\.|,|$)",
        ]:
            m = re.search(pattern, text)
            if m:
                candidate = m.group(1).strip()
                if len(candidate) <= 50 and len(candidate) > 2:
                    return candidate

        # Look for known topic keywords
        for keyword in sorted(_RELATED_TERM_MAP.keys(), key=len, reverse=True):
            if keyword in text:
                return keyword

        # Fallback: use first 3-5 words
        words = original.split()
        return " ".join(words[:5]) if words else "video"

    def _extract_related_queries(self, text: str, primary: str) -> list[str]:
        """Extract related search terms based on keyword mapping."""
        related = []
        for keyword, terms in _RELATED_TERM_MAP.items():
            if keyword in text or keyword in primary.lower():
                for term in terms:
                    if term not in related and term != primary.lower():
                        related.append(term)
                break

        # Add primary-based related terms
        primary_lower = primary.lower()
        if primary_lower not in related:
            related.insert(0, f"{primary} update")
            related.insert(1, f"{primary} tutorial")

        return related[:8]

    def _extract_excluded_terms(self, text: str) -> list[str]:
        """Extract terms to exclude based on intent keywords."""
        excluded = []
        for keyword, terms in _EXCLUDED_TERM_MAP.items():
            if keyword in text:
                excluded.extend(terms)

        if "low" in text and "value" in text:
            excluded.append("low value")
        if "spam" in text:
            excluded.append("spam")
        if "clickbait" in text:
            excluded.append("clickbait")

        # Deduplicate
        seen = set()
        result = []
        for term in excluded:
            if term not in seen:
                seen.add(term)
                result.append(term)
        return result[:10]

    def _extract_required_terms(self, text: str, primary: str) -> list[str]:
        """Extract required terms — usually empty in Phase 1."""
        required = []
        if "must include" in text or "must have" in text:
            m = re.search(r"must include\s+(.+?)(?:\.|,|$)", text)
            if m:
                required = [m.group(1).strip()]
        return required

    def _extract_languages(self, text: str) -> list[str]:
        """Extract preferred languages from intent."""
        languages = []
        for keyword, langs in _LANGUAGE_MAP.items():
            if keyword in text:
                for lang in langs:
                    if lang not in languages:
                        languages.append(lang)
        return languages[:4]

    def classify_videos(
        self,
        videos: list,
        rules: QueryRule,
    ) -> list[VideoClassification]:
        """Classify videos as strong/possible/noise match based on keywords."""
        classifications = []
        primary_lower = rules.primary_query.lower()
        excluded_lower = [t.lower() for t in rules.excluded_terms]

        for video in videos:
            title_lower = video.title.lower()
            desc_lower = video.description.lower()
            combined = title_lower + " " + desc_lower

            # Check for excluded terms
            has_excluded = any(term in combined for term in excluded_lower)

            # Check for primary match
            primary_matches = combined.count(primary_lower)

            # Check for related terms
            related_matches = 0
            for term in rules.related_queries:
                if term.lower() in combined:
                    related_matches += 1

            reasons = []
            if primary_matches > 0:
                reasons.append(f"contains primary query '{rules.primary_query}'")
            if related_matches > 0:
                reasons.append(f"matches {related_matches} related term(s)")
            if has_excluded:
                reasons.append("contains excluded term")

            if has_excluded and primary_matches == 0:
                match_level = "noise"
            elif primary_matches >= 2 or (primary_matches >= 1 and related_matches >= 2):
                match_level = "strong"
            elif primary_matches >= 1:
                match_level = "possible"
            else:
                match_level = "noise"
                reasons.append("no primary or related terms found")

            classifications.append(VideoClassification(
                video_id=video.id,
                match_level=match_level,
                reasons=reasons,
                is_excluded_candidate=has_excluded,
            ))

        return classifications

    def suggest_rule_changes(
        self,
        feedback: list[tuple[str, bool]],
        rules: QueryRule,
    ) -> RuleChangeProposal:
        """Propose rule changes based on relevant/irrelevant feedback."""
        added_excluded = []
        added_related = []

        for video_id, is_relevant in feedback:
            if not is_relevant:
                # Suggest excluding terms from the video title
                # In the fake provider, we don't have video titles here,
                # so we suggest common noise terms
                if "reaction" not in rules.excluded_terms:
                    added_excluded.append("reaction")
                if "shorts" not in rules.excluded_terms:
                    added_excluded.append("shorts")
                if "meme" not in rules.excluded_terms:
                    added_excluded.append("meme")

        rationale = (
            f"Based on {len(feedback)} feedback items "
            f"({sum(1 for _, r in feedback if r)} relevant, "
            f"{sum(1 for _, r in feedback if not r)} irrelevant). "
            "Proposed changes require user approval before application."
        )

        return RuleChangeProposal(
            added_excluded_terms=added_excluded,
            added_related_queries=added_related,
            exclude_shorts=True,
            rationale=rationale,
        )

    def structure_record(
        self,
        rough_notes: str,
    ) -> RecordStructureProposal:
        """Turn rough viewing notes into a structured proposal."""
        notes = rough_notes.strip()

        # Extract title: first line or first sentence
        lines = [l.strip() for l in notes.split("\n") if l.strip()]
        title = lines[0][:200] if lines else ""

        # Extract summary: first paragraph
        paragraphs = notes.split("\n\n")
        summary = paragraphs[0][:1000] if paragraphs else ""

        # Extract reflection: look for reflection-like content
        reflection = ""
        learned = ""
        agreement = ""
        disagreement = ""
        uncertainty = ""
        plan = ""
        tags = []
        timestamps = []
        rating = None

        # Parse structured markers
        for line in lines:
            lower = line.lower()
            if lower.startswith("reflection:") or lower.startswith("thoughts:"):
                reflection = line.split(":", 1)[1].strip()[:5000]
            elif lower.startswith("learned:") or lower.startswith("learning:"):
                learned = line.split(":", 1)[1].strip()[:5000]
            elif lower.startswith("agree:") or lower.startswith("agreement:"):
                agreement = line.split(":", 1)[1].strip()[:5000]
            elif lower.startswith("disagree:") or lower.startswith("disagreement:"):
                disagreement = line.split(":", 1)[1].strip()[:5000]
            elif lower.startswith("uncertain:") or lower.startswith("uncertainty:"):
                uncertainty = line.split(":", 1)[1].strip()[:5000]
            elif lower.startswith("plan:") or lower.startswith("todo:") or lower.startswith("follow-up:"):
                plan = line.split(":", 1)[1].strip()[:5000]
            elif lower.startswith("rating:") or lower.startswith("star:"):
                try:
                    rating = int(line.split(":", 1)[1].strip().split("/")[0])
                    rating = max(1, min(5, rating))
                except (ValueError, IndexError):
                    pass
            elif lower.startswith("tags:") or lower.startswith("tag:"):
                tag_text = line.split(":", 1)[1].strip()
                tags = [t.strip() for t in tag_text.split(",") if t.strip()]
            elif lower.startswith("timestamp:") or lower.startswith("time:"):
                ts_text = line.split(":", 1)[1].strip()
                # Parse like "2:30" or "150" or "2:30 - label"
                m = re.match(r"(\d+):(\d+)\s*(?:-\s*(.+))?", ts_text)
                if m:
                    seconds = int(m.group(1)) * 60 + int(m.group(2))
                    label = m.group(3) or ""
                    timestamps.append({"timestamp_seconds": seconds, "label": label})
                else:
                    try:
                        seconds = int(ts_text.split()[0])
                        timestamps.append({"timestamp_seconds": seconds, "label": ""})
                    except ValueError:
                        pass

        # Extract tags from #hashtags in the text
        if not tags:
            hashtag_tags = re.findall(r"#(\w+)", notes)
            tags = list(dict.fromkeys(hashtag_tags))[:50]

        # If no structured markers, use the whole text as reflection
        if not reflection and not learned and not plan:
            reflection = notes[:5000]

        return RecordStructureProposal(
            title=title,
            summary=summary,
            reflection=reflection,
            learned_point=learned,
            agreement=agreement,
            disagreement=disagreement,
            uncertainty=uncertainty,
            follow_up_plan=plan,
            tags=tags,
            timestamp_references=timestamps,
            rating=rating,
        )

    def suggest_title_summary(
        self,
        rough_notes: str,
    ) -> tuple[str, str]:
        """Suggest a title and summary for a private record."""
        proposal = self.structure_record(rough_notes)
        return proposal.title, proposal.summary
