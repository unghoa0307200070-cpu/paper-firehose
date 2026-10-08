"""Regression cases for the user's process-analysis recommendation scope."""
import unittest
from pathlib import Path
import yaml
from paper_firehose.processors.relevance import RelevancePolicy, evidence_text


class MultimodalRelevanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        topic = yaml.safe_load((root / 'github_actions_config/topics/perovskites.yaml').read_text(encoding='utf-8'))
        cls.policy = RelevancePolicy(topic['relevance'])

    def test_rejects_reported_off_topic_recommendations(self):
        examples = [
            ('Near-infrared AIE nanoprobes for imaging of bacterial septic arthritis', 'NIR imaging and antibacterial therapy'),
            ('Evaporation dynamics of acoustically levitated liquid marbles', 'Particle shell, image visualization and relative humidity'),
            ('Magneto-phototherapy using cysteine-modified FePt nanoparticles', ''),
            ('Interphase coupling of gas-droplet flows using a fully Lagrangian approach', 'Numerical particle tracking and kernel regression'),
            ('A review of plant disease datasets for precision agriculture', 'Computer vision and image processing'),
            ('MG-VQA: Manipulation Grounded Visual Question Answering with VLMs', 'Tablet objects and quality identification'),
            ('Stock price prediction with multimodal data fusion', ''),
        ]
        for title, summary in examples:
            with self.subTest(title=title):
                self.assertIsNone(self.policy.evaluate(dict(title=title, summary=summary)))

    def test_preserves_individual_modalities_and_process_fusion(self):
        titles = [
            'In-line NIR spectroscopy for pharmaceutical tablet content uniformity monitoring',
            'Real-time acoustic emission and vibration monitoring of fluidized-bed granulation',
            'Camera bubble and foam size measurement in gelatin production',
            'Multimodal Raman and machine vision process analytical technology for granulation',
            'TabNet versus chemometrics in NIR and Raman spectroscopy: Robustness and interpretability',
            'Antifogging coatings for optical windows in humid environments',
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertIsNotNone(self.policy.evaluate(dict(title=title)))

    def test_citation_metadata_is_not_process_evidence(self):
        citation = '<p>Publication date: 2027</p><p><b>Source:</b> Pharmaceutical Journal</p><p>Author(s): Raman X</p>'
        self.assertEqual(evidence_text(citation), '')
        self.assertIsNone(self.policy.evaluate(dict(title='Near infrared nanoprobe imaging', summary=citation)))

    def test_direct_process_detection_has_priority_over_generic_methods(self):
        direct = self.policy.evaluate(dict(title='Raman sensor data fusion for tablet content uniformity detection'))
        generic = self.policy.evaluate(dict(title='Calibration transfer in near infrared spectroscopy'))
        self.assertGreater(direct['priority'], generic['priority'])
        self.assertGreater(direct['boost'], generic['boost'])


if __name__ == '__main__':
    unittest.main()
