import unittest
from agents.journalist_agent import score_relevance, select_top_videos, KEYWORDS_CHILE

class TestJournalistScoring(unittest.TestCase):
    
    def test_score_relevance_high(self):
        title = "Pronóstico del Campeonato Chileno: Previa Colo Colo vs U de Chile"
        desc = "Mis predicciones para la fecha 5 de la primera división de chile."
        result = score_relevance(title, desc, KEYWORDS_CHILE)
        self.assertGreater(result["score"], 0.5)
        self.assertIn("pronóstico", result["matched_keywords"])
        self.assertIn("campeonato chileno", result["matched_keywords"])

    def test_score_relevance_low(self):
        title = "Video gracioso de gatos chilenos"
        desc = "No tiene nada que ver con fútbol."
        result = score_relevance(title, desc, KEYWORDS_CHILE)
        self.assertEqual(result["score"], 0.0)

    def test_select_top_videos_order(self):
        # Simular candidatos
        candidates = [
            {
                "video_id": "v1",
                "published_at": "2026-01-01T10:00:00Z",
                "reputation": {"score": 0.5},
                "relevance": {"score": 0.8}
            },
            {
                "video_id": "v2", 
                "published_at": "2026-01-02T10:00:00Z", # Más nuevo
                "reputation": {"score": 1.0}, # Whitelist
                "relevance": {"score": 0.9}
            },
            {
                "video_id": "v3",
                "published_at": "2025-12-31T10:00:00Z",
                "reputation": {"score": 0.3},
                "relevance": {"score": 0.3}
            }
        ]
        
        selected = select_top_videos(candidates, "CHI1", n=2)
        self.assertEqual(len(selected), 2)
        # El primero debe ser 'v2' por reputación whitelist
        self.assertEqual(selected[0]["video_id"], "v2")
        # El segundo debe ser 'v1' por relevancia
        self.assertEqual(selected[1]["video_id"], "v1")

if __name__ == "__main__":
    unittest.main()
