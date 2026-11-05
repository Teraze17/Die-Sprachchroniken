import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import Engine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.e=Engine(Path(self.tmp.name)/"test.sqlite3")

    def tearDown(self):
        self.e.db.close()
        self.tmp.cleanup()

    def test_isolation_persistence(self):
        self.e.add_record("alice","diary","Ich bin hier.")
        self.assertEqual(len(self.e.export("alice")["records"]),1)
        self.assertEqual(len(self.e.export("bob")["records"]),0)

    def test_answer_xp_and_unlock(self):
        q=self.e.get_question("a","Verben")
        correct,_,_=self.e.answer("a",q["id"],q["answer"])
        self.assertTrue(correct)
        self.assertEqual(self.e.profile("a")["xp"],10)

    def test_import_once_and_partial(self):
        rid=self.e.add_record("a","diary","Gestern ich habe gelernt.")
        exp=self.e.export("a")
        payload={"schema_version":"1.0","batch_id":exp["batch_id"],"user_id":"a","corrections":[{"record_id":rid,"status":"incorrect","corrected":"Gestern habe ich gelernt.","errors":[{"category":"Satzbau","topic":"V2"}]}],"questions":[{"question_id":"NEW-001","type":"multiple_choice","skill":"Kasus","question":"mit ___ Mann","options":["dem","den"],"answer":"dem"}],"quests":[],"culture_updates":[{"node_id":"GEOG-01","state":1}]}
        self.assertEqual(self.e.import_preview("a",payload)["corrections"],1)
        self.e.import_apply("a",payload)
        self.assertEqual(self.e.profile("a")["pending"],0)
        self.assertEqual([x for x in self.e.culture("a") if x["id"]=="GEOG-01"][0]["state"],1)
        with self.assertRaises(ValueError):self.e.import_apply("a",payload)

    def test_bad_import_rejected(self):
        ex=self.e.export("a")
        bad={"schema_version":"1.0","batch_id":ex["batch_id"],"user_id":"a","corrections":[],"questions":[{"question_id":"X","type":"multiple_choice","skill":"Kasus","question":"test","options":["a","b"],"answer":"c"}]}
        with self.assertRaises(ValueError):self.e.import_preview("a",bad)


if __name__=="__main__":unittest.main()
