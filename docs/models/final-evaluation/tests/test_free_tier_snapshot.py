"""Validate exact Owner-provided free-tier snapshot for final B14 model evaluation."""
from pathlib import Path
import json
import unittest

HERE=Path(__file__).resolve().parents[1]
DATA=HERE/"GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.json"
DOC=HERE/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
OVERVIEW=HERE/"GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.md"
REGISTRY=HERE.parents[2]/"apps/korean-ai-platform/app/pilot/b14_models.json"

class GoogleFreeTierSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(DATA.read_text(encoding="utf-8"))
        cls.models={x["display_name"]:x for x in cls.data["models"]}
        cls.tools={(x["display_name"],x["tool_type"]):x for x in cls.data["tools"]}
        cls.registered=json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.doc=DOC.read_text(encoding="utf-8")
        cls.overview=OVERVIEW.read_text(encoding="utf-8")

    def test_complete_user_snapshot(self):
        self.assertEqual(len(self.models),45)
        self.assertEqual(len(self.tools),21)
        self.assertEqual(self.data["tier"],"free")
        self.assertEqual(self.data["snapshot_date"],"2026-10-09")
        self.assertEqual(len(self.data["b14_registered_google_display_mapping"]),4)

    def test_four_b14_google_ids_are_only_active_registry_links(self):
        registered={x["id"] for x in self.registered["models"]}
        self.assertEqual(len(registered),9)
        self.assertTrue(set(self.data["b14_registered_google_display_mapping"]).issubset(registered))
        expected={
          "google/gemini-3.1-flash-lite":(15,250000,500),
          "google/gemini-3.5-flash-lite":(15,250000,500),
          "google/gemma-4-26b-a4b-it":(30,16000,14400),
          "google/gemma-4-31b-it":(30,16000,14400),
        }
        for model_id,name in self.data["b14_registered_google_display_mapping"].items():
            with self.subTest(model_id=model_id):
                m=self.models[name]
                self.assertEqual((m["rpm"],m["input_tpm"],m["rpd"]),expected[model_id])
                self.assertIn(model_id,self.doc)
                self.assertIn(model_id,self.overview)

    def test_zero_not_equal_to_missing_not_equal_to_unlimited(self):
        self.assertEqual(self.models["Gemini 3.1 Pro"]["rpm"],0)
        self.assertIsNone(self.models["Veo 3 Generate"]["input_tpm"])
        self.assertEqual(self.models["Gemini 3 Flash Live"]["rpm"],"unlimited")
        self.assertEqual(self.models["Gemini 2.5 Flash Native Audio Dialog"]["input_tpm"],1000000)
        self.assertEqual(self.models["Gemini 2.5 Flash"]["rpd"],20)

    def test_tools_are_separate_quota_dimension(self):
        self.assertEqual(self.tools[("Gemini 3.1 Flash Lite","map_grounding")]["rpd"],500)
        self.assertEqual(self.tools[("Gemini 3.5 Flash Lite","map_grounding")]["rpd"],500)
        self.assertEqual(self.tools[("Gemini 3","search_grounding")]["rpd"],0)
        self.assertEqual(self.tools[("Default","search_grounding")]["rpd"],1500)

    def test_no_old_41_case_results_imported_into_final_grade(self):
        self.assertIn("과거의 41회 비교 점수를 가져온 것이 아니다",self.doc)
        self.assertNotIn("7/10",self.overview)
        self.assertIn("QKR-002",self.doc)
        self.assertIn("7/10",self.doc)
        self.assertIn("8/10",self.doc)
        self.assertIn("F6 고객용 견적 PDF",self.doc)

if __name__=="__main__":
    unittest.main()
