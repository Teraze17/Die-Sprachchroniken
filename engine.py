"""Persistent, API-free learning engine for Die Sprachchroniken."""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from streak_chart import summarize_streaks

TZ = ZoneInfo("Asia/Taipei")
SKILLS = {"Satzbau", "Kasus", "Verben", "Adjektive", "Praepositionen", "Nebensaetze", "Wortschatz", "Sprechen", "Schreiben", "Lesen", "Hoeren", "Wortbildung"}
CULTURES = {"Feste", "Gesellschaft", "Geografie", "Alltag", "Geschichte"}
RANKS = [(1, "Dorfbewohner"), (11, "Abenteurer"), (21, "Ritter"), (36, "Baron"), (51, "Herzog"), (71, "Kaiser")]

SEED_QUESTIONS = [
    ("Q-SEED-01", "multiple_choice", "Kasus", "Ich fahre mit ___ Freund nach Berlin.", ["mein", "meinen", "meinem", "meiner"], "meinem", "mit requires Dativ; Freund is masculine.", "A2"),
    ("Q-SEED-02", "multiple_choice", "Satzbau", "Gestern ___ ich einen Film gesehen.", ["habe", "ich habe", "hat", "bin"], "habe", "The conjugated verb occupies position 2 in a main clause.", "A2"),
    ("Q-SEED-03", "multiple_choice", "Verben", "Du ___ heute nach Berlin.", ["fahrt", "fahrst", "fährst", "fahren"], "fährst", "fahren changes a to ä for du in Präsens.", "A2"),
    ("Q-SEED-04", "multiple_choice", "Wortschatz", "Was bedeutet 'unvorhersehbar'?", ["predictable", "unpredictable", "unfriendly", "unnecessary"], "unpredictable", "un- negates vorhersehbar (predictable).", "B1"),
    ("Q-SEED-05", "multiple_choice", "Nebensaetze", "Ich bleibe zu Hause, weil ich krank ___.", ["bin", "ist", "sein", "bist"], "bin", "A weil clause places its conjugated verb at the end.", "A2"),
    ("Q-SEED-06", "multiple_choice", "Kasus", "Ich bin mit ___ Entscheidung zufrieden.", ["die", "der", "den", "das"], "der", "mit takes Dativ; feminine die becomes der.", "B1"),
]

CULTURE_NODES = {
    "Feste": [("FEST-01", "Weihnachtsmarkt", "Deutschland"), ("FEST-02", "Ostern", "DACH"), ("FEST-03", "Karneval", "Deutschland"), ("FEST-04", "Tag der Deutschen Einheit", "Deutschland")],
    "Gesellschaft": [("GESE-01", "Bundesländer", "Deutschland"), ("GESE-02", "Ausbildung", "Deutschland"), ("GESE-03", "Krankenversicherung", "Deutschland"), ("GESE-04", "Sonntagsruhe", "Deutschland")],
    "Geografie": [("GEOG-01", "Heidelberg", "Deutschland"), ("GEOG-02", "Schwarzwald", "Deutschland"), ("GEOG-03", "Wien", "Österreich"), ("GEOG-04", "Zürich", "Schweiz")],
    "Alltag": [("ALLT-01", "Brotkultur", "DACH"), ("ALLT-02", "ÖPNV", "Deutschland"), ("ALLT-03", "Mülltrennung", "Deutschland"), ("ALLT-04", "Wohngemeinschaft", "DACH")],
    "Geschichte": [("GESCH-01", "Berliner Mauer", "Deutschland"), ("GESCH-02", "Goethe", "Deutschland"), ("GESCH-03", "Beethoven", "Deutschland"), ("GESCH-04", "Deutsche Wiedervereinigung", "Deutschland")],
}

# Offline, hand-checked short reading/listening scenarios.
# Each audio passage is spoken by a local German TTS voice; no API required.
MEDIA_BANK = [
    ("LES-01", "Lesen", "Morgen früh fährt Anna nach Heidelberg. Ihr Zug kommt um acht Uhr. Deshalb steht sie schon um sechs Uhr auf.", "Warum steht Anna früh auf?", ["Sie muss arbeiten.", "Sie fährt mit dem Zug.", "Sie besucht einen Arzt.", "Sie hat keine Schule."], "Sie fährt mit dem Zug.", "Der Text sagt: Ihr Zug kommt um acht Uhr; sie steht um sechs Uhr auf."),
    ("LES-02", "Lesen", "Im Dorf ist heute Sonntag. Die meisten Geschäfte sind geschlossen. Lukas geht deshalb mit seiner Schwester im Park spazieren.", "Was macht Lukas am Sonntag?", ["Er kauft Brot.", "Er fährt zur Arbeit.", "Er geht spazieren.", "Er besucht ein Museum."], "Er geht spazieren.", "Lukas geht im Park spazieren. So nutzt er den Sonntag."),
    ("LES-03", "Lesen", "Mira möchte einen Sprachkurs besuchen. Der Kurs beginnt am Dienstag und kostet fünfzig Euro pro Monat. Die Anmeldung ist online möglich.", "Wie kann Mira sich anmelden?", ["Im Restaurant", "Online", "Nur telefonisch", "Bei der Polizei"], "Online", "Die Anmeldung ist online möglich."),
    ("LES-04", "Lesen", "In unserer Wohngemeinschaft kochen wir oft zusammen. Paul kauft Gemüse und ich bereite die Soße zu. Nach dem Essen räumen alle die Küche auf.", "Wer räumt die Küche auf?", ["Nur Paul", "Niemand", "Alle", "Nur ich"], "Alle", "Im Text steht: Nach dem Essen räumen alle die Küche auf."),
    ("HOE-01", "Hoeren", "Guten Morgen! Der Zug nach Berlin fährt heute zehn Minuten später ab. Bitte bleiben Sie am Gleis drei.", "Wie viel Verspätung hat der Zug?", ["Fünf Minuten", "Zehn Minuten", "Zwanzig Minuten", "Dreißig Minuten"], "Zehn Minuten", "Im Hörtext: zehn Minuten später. Gleis drei ist die Bahnsteignummer."),
    ("HOE-02", "Hoeren", "Hallo Lena! Unser Treffen ist nicht um vier, sondern um fünf Uhr. Wir sehen uns vor der Bibliothek. Bis später!", "Wann treffen sich die Freunde?", ["Um drei Uhr", "Um vier Uhr", "Um fünf Uhr", "Um sechs Uhr"], "Um fünf Uhr", "Die Person korrigiert die Uhrzeit: nicht um vier, sondern um fünf Uhr."),
    ("HOE-03", "Hoeren", "Entschuldigung, ich suche die Apotheke. Gehen Sie zuerst geradeaus und biegen Sie dann links ab. Die Apotheke ist neben der Bank.", "Wo ist die Apotheke?", ["Hinter dem Bahnhof", "Neben der Bank", "Vor der Schule", "Im Supermarkt"], "Neben der Bank", "Die Apotheke ist neben der Bank."),
    ("HOE-04", "Hoeren", "Heute gibt es in unserer Mensa Kartoffelsuppe und Salat. Das Menü kostet sechs Euro. Nach zwölf Uhr ist es besonders voll.", "Wie viel kostet das Menü?", ["Vier Euro", "Fünf Euro", "Sechs Euro", "Sieben Euro"], "Sechs Euro", "Der Hörtext nennt sechs Euro für das Menü."),
]


def progress_bar(current:int,total:int,width:int=12):
    if total<=0:return "░"*width
    filled=min(width,max(0,int(width*max(0,current)/total)))
    return "█"*filled + "░"*(width-filled)


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Engine:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self._schema()

    def _schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, xp INTEGER NOT NULL DEFAULT 0, gold INTEGER NOT NULL DEFAULT 0, chapter INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,kind TEXT NOT NULL,prompt TEXT,response TEXT NOT NULL,source TEXT,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',batch_id TEXT);
        CREATE INDEX IF NOT EXISTS ix_records_user_status ON records(user_id,status);
        CREATE TABLE IF NOT EXISTS vocab(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,term TEXT NOT NULL,source TEXT,note TEXT,created_at TEXT NOT NULL,UNIQUE(user_id,term));
        CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,type TEXT NOT NULL,skill TEXT NOT NULL,prompt TEXT NOT NULL,options TEXT NOT NULL,answer TEXT,explanation TEXT,level TEXT,owner_id TEXT,package_id TEXT,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,question_id TEXT NOT NULL,response TEXT NOT NULL,correct INTEGER,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS skills(user_id TEXT NOT NULL,skill TEXT NOT NULL,correct INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,skill));
        CREATE TABLE IF NOT EXISTS corrections(record_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,status TEXT NOT NULL,corrected TEXT,errors TEXT NOT NULL,explanation TEXT,confidence TEXT,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS review_items(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source_id TEXT NOT NULL,skill TEXT NOT NULL,due_at TEXT NOT NULL,interval_days INTEGER NOT NULL DEFAULT 1,streak INTEGER NOT NULL DEFAULT 0,UNIQUE(user_id,source_id,skill));
        CREATE TABLE IF NOT EXISTS culture_nodes(id TEXT PRIMARY KEY,category TEXT NOT NULL,title TEXT NOT NULL,country TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS culture_progress(user_id TEXT NOT NULL,node_id TEXT NOT NULL,state INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,node_id));
        CREATE TABLE IF NOT EXISTS quests(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,skill TEXT,trigger_kind TEXT NOT NULL DEFAULT 'available',trigger_value TEXT,status TEXT NOT NULL DEFAULT 'locked',xp INTEGER NOT NULL DEFAULT 30,gold INTEGER NOT NULL DEFAULT 10,package_id TEXT);
        CREATE TABLE IF NOT EXISTS packages(batch_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,payload_hash TEXT NOT NULL,imported_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS exports(batch_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS world_flags(user_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(user_id,key));
        CREATE TABLE IF NOT EXISTS quiz_progress(
          user_id TEXT NOT NULL, question_id TEXT NOT NULL,
          correct_count INTEGER NOT NULL DEFAULT 0, wrong_count INTEGER NOT NULL DEFAULT 0,
          streak INTEGER NOT NULL DEFAULT 0, last_seen TEXT NOT NULL, due_at TEXT NOT NULL,
          PRIMARY KEY(user_id, question_id));
        CREATE INDEX IF NOT EXISTS ix_quiz_due ON quiz_progress(user_id,due_at);
        CREATE TABLE IF NOT EXISTS quest_progress(
          user_id TEXT NOT NULL, quest_id TEXT NOT NULL, phase INTEGER NOT NULL DEFAULT 0,
          baseline_attempts INTEGER NOT NULL DEFAULT 0, npc_record_id TEXT,
          PRIMARY KEY(user_id, quest_id));
        CREATE TABLE IF NOT EXISTS quest_attempts(user_id TEXT NOT NULL,quest_id TEXT NOT NULL,question_id TEXT NOT NULL,
            PRIMARY KEY(user_id,quest_id,question_id));
        CREATE TABLE IF NOT EXISTS reminder_preferences(
          user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS reminder_deliveries(
          user_id TEXT NOT NULL, cutoff_date TEXT NOT NULL, result TEXT NOT NULL,
          attempted_at TEXT NOT NULL, PRIMARY KEY(user_id,cutoff_date));
        CREATE TABLE IF NOT EXISTS activity_log(
          id TEXT PRIMARY KEY,user_id TEXT NOT NULL,kind TEXT NOT NULL,
          title TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',xp_delta INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_activity_recent ON activity_log(user_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS vocab_review(
          user_id TEXT NOT NULL,vocab_id TEXT NOT NULL,
          recalled INTEGER NOT NULL DEFAULT 0,forgotten INTEGER NOT NULL DEFAULT 0,
          streak INTEGER NOT NULL DEFAULT 0,last_seen TEXT NOT NULL,due_at TEXT NOT NULL,
          PRIMARY KEY(user_id,vocab_id));
        CREATE TABLE IF NOT EXISTS media_passages(question_id TEXT PRIMARY KEY,passage TEXT NOT NULL,mode TEXT NOT NULL);
        """)
        with self.db:
            for qid, typ, skill, prompt, options, answer, expl, level in SEED_QUESTIONS:
                self.db.execute("INSERT OR IGNORE INTO questions(id,type,skill,prompt,options,answer,explanation,level) VALUES(?,?,?,?,?,?,?,?)",(qid,typ,skill,prompt,dumps(options),answer,expl,level))
            extra_bank = Path(__file__).with_name("questions_v1_4.json")
            if extra_bank.exists():
                for qid, skill, prompt, options, answer, explanation, level in json.loads(extra_bank.read_text(encoding="utf-8")):
                    self.db.execute("INSERT OR IGNORE INTO questions(id,type,skill,prompt,options,answer,explanation,level) VALUES(?,?,?,?,?,?,?,?)",
                                    (qid,"multiple_choice",skill,prompt,dumps(options),answer,explanation,level))
            for qid, skill, passage, question, options, answer, explanation in MEDIA_BANK:
                self.db.execute("INSERT OR IGNORE INTO questions(id,type,skill,prompt,options,answer,explanation,level) VALUES(?,?,?,?,?,?,?,?)",
                    (qid,"multiple_choice",skill,question,dumps(options),answer,explanation,"A2-B1"))
                self.db.execute("INSERT OR IGNORE INTO media_passages VALUES(?,?,?)",(qid,passage,skill))
            for category, nodes in CULTURE_NODES.items():
                for node_id,title,country in nodes:
                    self.db.execute("INSERT OR IGNORE INTO culture_nodes VALUES(?,?,?,?)",(node_id,category,title,country))
        # Migrate existing V1.3 attempts once without losing saved answers or XP.
        # SQLite stores attempts historically; this table is a scheduling cache.
        self._backfill_quiz_progress()
        self._backfill_activity()

    def _backfill_quiz_progress(self):
        rows = self.db.execute("SELECT user_id,question_id,correct,created_at FROM attempts ORDER BY created_at,rowid").fetchall()
        history = {}
        for r in rows:
            k=(r["user_id"],r["question_id"])
            stat=history.setdefault(k,{"correct":0,"wrong":0,"streak":0,"last":r["created_at"],"last_correct":False})
            good=bool(r["correct"])
            stat["correct" if good else "wrong"]+=1
            stat["streak"]=stat["streak"]+1 if good else 0
            stat["last"]=r["created_at"]
            stat["last_correct"]=good
        with self.db:
            for (user,qid),v in history.items():
                try: stamp=datetime.fromisoformat(v["last"])
                except (TypeError,ValueError): stamp=datetime.now(TZ)
                if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=TZ)
                delay=timedelta(days=self._interval_days(v["streak"])) if v["last_correct"] else timedelta(minutes=10)
                self.db.execute("INSERT OR IGNORE INTO quiz_progress(user_id,question_id,correct_count,wrong_count,streak,last_seen,due_at) VALUES(?,?,?,?,?,?,?)",
                    (user,qid,v["correct"],v["wrong"],v["streak"],v["last"],(stamp+delay).isoformat(timespec="seconds")))

    def _backfill_activity(self):
        # Keep historical learning actions visible, without awarding XP again.
        # Avoid guessing timestamps for old quest completions (quests have no finish timestamp).
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO activity_log(id,user_id,kind,title,detail,xp_delta,created_at)
                SELECT 'legacy-record-'||id,user_id,kind,'紀錄德文',response,0,created_at FROM records""")
            self.db.execute("""INSERT OR IGNORE INTO activity_log(id,user_id,kind,title,detail,xp_delta,created_at)
                SELECT 'legacy-vocab-'||id,user_id,'vocab','收藏單字',term,0,created_at FROM vocab""")
            self.db.execute("""INSERT OR IGNORE INTO activity_log(id,user_id,kind,title,detail,xp_delta,created_at)
                SELECT 'legacy-attempt-'||id,user_id,'quiz',
                       CASE WHEN correct=1 THEN '答對文法題' ELSE '文法題待複習' END,
                       question_id||' · '||response, CASE WHEN correct=1 THEN 10 ELSE 0 END,created_at
                FROM attempts""")

    def _activity(self,user_id,kind,title,detail='',xp_delta=0,activity_id=None):
        self.db.execute("INSERT OR IGNORE INTO activity_log VALUES(?,?,?,?,?,?,?)",
            (activity_id or 'ACT-'+uuid.uuid4().hex[:16],str(user_id),kind,title,str(detail)[:2000],xp_delta,now()))

    def activity(self,user_id,day=None,limit=35):
        self.user(user_id)
        day=day or datetime.now(TZ).date().isoformat()
        rows=self.db.execute("""SELECT * FROM activity_log WHERE user_id=? AND substr(created_at,1,10)=?
           ORDER BY created_at DESC,rowid DESC LIMIT ?""",(str(user_id),day,limit)).fetchall()
        return [dict(r) for r in rows]

    def activity_summary(self,user_id,day=None):
        self.user(user_id)
        day=day or datetime.now(TZ).date().isoformat()
        rows=self.db.execute("""SELECT kind,COUNT(*) n,COALESCE(SUM(xp_delta),0) xp FROM activity_log
             WHERE user_id=? AND substr(created_at,1,10)=? GROUP BY kind""",(str(user_id),day)).fetchall()
        return {'day':day,'events':sum(r['n'] for r in rows),'xp':sum(r['xp'] for r in rows),
                'kinds':{r['kind']:r['n'] for r in rows}}

    def streak_stats(self,user_id,today:date|None=None):
        """Study activity heatmap, derived from saved events (no schema change)."""
        today=today or datetime.now(TZ).date()
        rows=self.db.execute("""SELECT substr(created_at,1,10) day,COUNT(*) n
            FROM activity_log WHERE user_id=? AND substr(created_at,1,10)<=?
            GROUP BY substr(created_at,1,10)""",(str(user_id),today.isoformat())).fetchall()
        counts={date.fromisoformat(r['day']):r['n'] for r in rows}
        return summarize_streaks(counts,today)

    def overview(self,user_id):
        p=self.profile(user_id)
        all_quests=self.db.execute("SELECT kind,status FROM quests WHERE user_id=?",(str(user_id),)).fetchall()
        main_total=sum(q['kind']=='main' for q in all_quests)
        main_done=sum(q['kind']=='main' and q['status']=='completed' for q in all_quests)
        culture=self.culture(user_id)
        discovered=sum(r['state']>0 for r in culture)
        mastered=sum(r['state']==3 for r in culture)
        qb=self.db.execute("""SELECT COUNT(*) n FROM questions q WHERE q.enabled=1 AND q.type='multiple_choice'
            AND q.skill NOT IN ('Lesen','Hoeren') AND (q.owner_id IS NULL OR q.owner_id=?)""",(str(user_id),)).fetchone()['n']
        learned=self.db.execute("""SELECT COUNT(*) n FROM quiz_progress p JOIN questions q ON q.id=p.question_id
            WHERE p.user_id=? AND q.enabled=1 AND q.skill NOT IN ('Lesen','Hoeren')""",(str(user_id),)).fetchone()['n']
        voc_total=self.db.execute("SELECT COUNT(*) FROM vocab WHERE user_id=?",(str(user_id),)).fetchone()[0]
        voc_recalled=self.db.execute("SELECT COUNT(*) FROM vocab_review WHERE user_id=? AND streak>=2",(str(user_id),)).fetchone()[0]
        # Limited to content in this V1 map; not a CEFR completion score.
        components=[(main_done,max(1,main_total)),(discovered,max(1,len(culture))),(learned,max(1,qb))]
        overall=round(100*sum(x/y for x,y in components)/len(components))
        return dict(profile=p,main_done=main_done,main_total=main_total,culture_discovered=discovered,
                    culture_mastered=mastered,culture_total=len(culture),quiz_seen=learned,quiz_total=qb,
                    vocab_total=voc_total,vocab_recalled=voc_recalled,overall=overall,today=self.activity_summary(user_id))

    def vocab_pick(self,user_id):
        self.user(user_id)
        rows=self.db.execute("""SELECT v.*,r.streak,r.due_at,r.forgotten FROM vocab v
          LEFT JOIN vocab_review r ON r.vocab_id=v.id AND r.user_id=v.user_id
          WHERE v.user_id=? ORDER BY v.created_at DESC""",(str(user_id),)).fetchall()
        due=[r for r in rows if not r['due_at'] or r['due_at']<=now()]
        if not due:return None
        fresh=[r for r in due if not r['due_at']]
        if fresh:return random.choice(fresh)
        weak=[r for r in due if not r['streak']]
        return random.choice(weak if weak else due)

    def vocab_grade(self,user_id,vocab_id,recalled,response=None):
        self.user(user_id)
        vocab=self.db.execute("SELECT * FROM vocab WHERE id=? AND user_id=?",(vocab_id,str(user_id))).fetchone()
        if not vocab:raise ValueError("找不到這張個人單字卡。")
        old=self.db.execute("SELECT * FROM vocab_review WHERE vocab_id=? AND user_id=?",(vocab_id,str(user_id))).fetchone()
        if old and old['due_at']>now():raise ValueError("這張卡片尚未到期，稍後再複習。")
        streak=(int(old['streak'])+1 if old and recalled else int(bool(recalled)))
        due=(datetime.now(TZ)+(timedelta(days=self._interval_days(streak)) if recalled else timedelta(minutes=10))).isoformat(timespec='seconds')
        with self.db:
            self.db.execute("""INSERT INTO vocab_review VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(user_id,vocab_id) DO UPDATE SET
               recalled=recalled+excluded.recalled,forgotten=forgotten+excluded.forgotten,
               streak=excluded.streak,last_seen=excluded.last_seen,due_at=excluded.due_at""",
               (str(user_id),vocab_id,int(bool(recalled)),int(not recalled),streak,now(),due))
            self._activity(user_id,'vocab_review','單字主動回想' if recalled else '單字待加強',
                vocab['term']+(('｜輸入：'+response[:150]) if response is not None else '｜自行評估'))
        return {'term':vocab['term'],'streak':streak,'due_at':due}

    def media(self,question_id):
        row=self.db.execute("SELECT * FROM media_passages WHERE question_id=?",(question_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _interval_days(streak):
        return [1,3,7,14,30,60][min(max(streak-1,0),5)]

    def user(self, user_id):
        user_id = str(user_id)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO users(user_id,created_at) VALUES(?,?)",(user_id,now()))
            self.db.execute("INSERT OR IGNORE INTO reminder_preferences(user_id,enabled) VALUES(?,1)",(user_id,))
            self.db.execute("INSERT OR IGNORE INTO quests(id,user_id,kind,title,description,skill,status,xp,gold) VALUES(?,?,?,?,?,?,?,?,?)",(f"MAIN-{user_id}-01",user_id,"main","Das Erwachen","前往公會圖書館，與學者艾爾文相遇，通過入門試煉並說出第一句德文。","Wortschatz","available",80,20))
            self.db.execute("INSERT OR IGNORE INTO quests(id,user_id,kind,title,description,skill,trigger_kind,trigger_value,status,xp,gold) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(f"SIDE-{user_id}-01",user_id,"side","Ein seltsamer Brief","酒館裡的旅行者莉娜遺失了信件，請用禮貌的德文協助她。","Satzbau","attempts","3","locked",40,10))
            self.db.execute("INSERT OR IGNORE INTO quests(id,user_id,kind,title,description,skill,trigger_kind,trigger_value,status,xp,gold) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (f"MAIN-{user_id}-02",user_id,"main","Die Karte der fünf Reiche","探索公會古地圖與五大文化領土，尋找失落的圖書館線索。","Kasus","quest",f"MAIN-{user_id}-01","locked",90,25))
            self.db.execute("INSERT OR IGNORE INTO quests(id,user_id,kind,title,description,skill,trigger_kind,trigger_value,status,xp,gold) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (f"MAIN-{user_id}-03",user_id,"main","Der Schlüssel des Archivs","在古代檔案館尋找一把鑰匙，選擇你將相信的盟友。","Nebensaetze","quest",f"MAIN-{user_id}-02","locked",100,30))
            # Old seed quests retain completion status, but gain readable descriptions.
            self.db.execute("UPDATE quests SET description=? WHERE id=? AND description=?",
                ("前往公會圖書館，與學者艾爾文相遇，通過入門試煉並說出第一句德文。",f"MAIN-{user_id}-01","Visit the guild library and complete your first German exercises."))
            self.db.execute("UPDATE quests SET description=? WHERE id=? AND description=?",
                ("酒館裡的旅行者莉娜遺失了信件，請用禮貌的德文協助她。",f"SIDE-{user_id}-01","Help a traveler use a polite German phrase."))
        return self.db.execute("SELECT * FROM users WHERE user_id=?",(user_id,)).fetchone()

    def add_record(self, user_id, kind, response, prompt=None, source=None):
        self.user(user_id)
        if not response.strip() or len(response)>4000:
            raise ValueError("文字須介於 1–4000 字元。")
        rid = "R-"+uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute("INSERT INTO records(id,user_id,kind,prompt,response,source,created_at) VALUES(?,?,?,?,?,?,?)",(rid,str(user_id),kind,prompt,response.strip(),source,now()))
            self._activity(user_id,kind,'寫冒險日誌' if kind=='diary' else '完成 NPC 回答' if kind=='free_answer' else '收藏句子',response.strip(),activity_id='legacy-record-'+rid)
        return rid

    def add_vocab(self, user_id, term, source="personal", note=""):
        self.user(user_id)
        if not term.strip() or len(term)>150:
            raise ValueError("單字長度須介於 1–150 字元。")
        vid = "V-"+uuid.uuid4().hex[:12]
        with self.db:
            cur=self.db.execute("INSERT OR IGNORE INTO vocab VALUES(?,?,?,?,?,?)",(vid,str(user_id),term.strip(),source,note,now()))
            if cur.rowcount:self._activity(user_id,'vocab','收藏單字',term.strip(),activity_id='legacy-vocab-'+vid)
        return vid if cur.rowcount else None

    def quiz_history(self,user_id,limit=12):
        self.user(user_id)
        return self.db.execute("""SELECT a.question_id,q.skill,q.prompt,a.response,a.correct,a.created_at
            FROM attempts a JOIN questions q ON q.id=a.question_id
            WHERE a.user_id=? ORDER BY a.rowid DESC LIMIT ?""",(str(user_id),limit)).fetchall()

    def quiz_overview(self,user_id,skill=None):
        self.user(user_id)
        query="""SELECT q.id,p.due_at FROM questions q
          LEFT JOIN quiz_progress p ON p.question_id=q.id AND p.user_id=?
          WHERE q.enabled=1 AND q.type='multiple_choice' AND (q.owner_id IS NULL OR q.owner_id=?)"""
        params=[str(user_id),str(user_id)]
        if skill:query+=" AND q.skill=?";params.append(skill)
        else:query+=" AND q.skill NOT IN ('Lesen','Hoeren')"
        rows=self.db.execute(query,params).fetchall()
        fresh=sum(r["due_at"] is None for r in rows)
        due=sum(r["due_at"] is not None and r["due_at"]<=now() for r in rows)
        future=[r["due_at"] for r in rows if r["due_at"] is not None and r["due_at"]>now()]
        return {"new":fresh,"due":due,"waiting":len(future),"next_due":min(future) if future else None}

    def get_question(self,user_id,skill=None,exclude_id=None):
        self.user(user_id)
        query="""SELECT q.*,p.correct_count,p.wrong_count,p.streak,p.due_at
          FROM questions q LEFT JOIN quiz_progress p
          ON p.user_id=? AND p.question_id=q.id
          WHERE q.enabled=1 AND (q.owner_id IS NULL OR q.owner_id=?) AND q.type='multiple_choice'"""
        params=[str(user_id),str(user_id)]
        if skill:query+=" AND q.skill=?";params.append(skill)
        else:query+=" AND q.skill NOT IN ('Lesen','Hoeren')"
        rows=self.db.execute(query,params).fetchall()
        valid=[]
        for q in rows:
            try:self._checked_options(q)
            except ValueError:continue
            if q["due_at"] is None or q["due_at"]<=now(): valid.append(q)
        if exclude_id and len(valid)>1:
            valid=[q for q in valid if q["id"]!=exclude_id]
        if not valid:return None
        # First present unseen material; then errors due for review; then successful due reviews.
        unseen=[q for q in valid if q["due_at"] is None]
        wrong=[q for q in valid if (q["wrong_count"] or 0)>0 and q["streak"]==0]
        if wrong and (not unseen or random.random()<0.35):return random.choice(wrong)
        if unseen:return random.choice(unseen)
        return random.choice(valid)

    @staticmethod
    def _normalized_answer(value):
        return value.strip().casefold()

    def _checked_options(self, q):
        """Reject ambiguous imported questions before users can be graded on them."""
        try:
            options = json.loads(q["options"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("題目選項資料有誤，請重新匯入題目。") from exc
        if (not isinstance(options, list) or not 2 <= len(options) <= 5 or
                not all(isinstance(o, str) and o.strip() for o in options)):
            raise ValueError("題目選項資料有誤，請重新匯入題目。")
        normalized = [self._normalized_answer(o) for o in options]
        if len(normalized) != len(set(normalized)):
            raise ValueError("這題出現重複選項，無法正確判分，請修正題庫。")
        expected = q["answer"]
        if not isinstance(expected, str) or self._normalized_answer(expected) not in normalized:
            raise ValueError("這題沒有有效的標準答案，請修正題庫。")
        return options

    def answer_choice(self,user_id,question_id,choice_index,quest_id=None):
        """Grade the actual zero-based button index, not any UI display text."""
        self.user(user_id)
        q=self.db.execute("SELECT * FROM questions WHERE id=? AND enabled=1 AND (owner_id IS NULL OR owner_id=?)",(question_id,str(user_id))).fetchone()
        if not q:raise ValueError("題目不存在或無法使用。")
        if q["type"]!="multiple_choice":raise ValueError("此題型尚不支援即時批改。")
        options=self._checked_options(q)
        if isinstance(choice_index,bool) or not isinstance(choice_index,int) or not 0<=choice_index<len(options):
            raise ValueError("無效的答案選項。")
        selected=options[choice_index]
        correct,expected,explanation=self.answer(user_id,question_id,selected,quest_id=quest_id)
        return correct,expected,explanation,selected

    def answer(self,user_id,question_id,answer,quest_id=None):
        self.user(user_id)
        q=self.db.execute("SELECT * FROM questions WHERE id=? AND enabled=1 AND (owner_id IS NULL OR owner_id=?)",(question_id,str(user_id))).fetchone()
        if not q:raise ValueError("題目不存在或無法使用。")
        if q["type"]!="multiple_choice":raise ValueError("此題型尚不支援即時批改。")
        options=self._checked_options(q)
        if not isinstance(answer,str) or self._normalized_answer(answer) not in [self._normalized_answer(o) for o in options]:
            raise ValueError("所選答案不在題目選項內。")
        correct=self._normalized_answer(answer)==self._normalized_answer(q["answer"])
        previous=self.db.execute("SELECT * FROM quiz_progress WHERE user_id=? AND question_id=?",(str(user_id),question_id)).fetchone()
        if previous and previous["due_at"]>now():
            raise ValueError("這道題目前不需要複習；先練習其他題目，等到期再回答。")
        streak=(previous["streak"]+1 if correct and previous else 1 if correct else 0)
        due=(datetime.now(TZ)+(timedelta(days=self._interval_days(streak)) if correct else timedelta(minutes=10))).isoformat(timespec="seconds")
        if quest_id:
            st=self.quest_state(user_id,quest_id)
            if st["quest"]["status"]!="active" or st["phase"]!=1:
                raise ValueError("此任務尚未進入文法試煉階段。")
        attempt_id='A-'+uuid.uuid4().hex[:12]
        with self.db:
            if quest_id:
                self.db.execute("INSERT OR IGNORE INTO quest_attempts(user_id,quest_id,question_id) VALUES(?,?,?)",
                                (str(user_id),quest_id,question_id))
            self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?)",(attempt_id,str(user_id),question_id,answer,int(correct),now()))
            self.db.execute("""INSERT INTO quiz_progress(user_id,question_id,correct_count,wrong_count,streak,last_seen,due_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,question_id) DO UPDATE SET
                correct_count=correct_count+excluded.correct_count,wrong_count=wrong_count+excluded.wrong_count,
                streak=excluded.streak,last_seen=excluded.last_seen,due_at=excluded.due_at""",
                (str(user_id),question_id,int(correct),int(not correct),streak,now(),due))
            self.db.execute("INSERT INTO skills(user_id,skill,correct,total) VALUES(?,?,?,1) ON CONFLICT(user_id,skill) DO UPDATE SET correct=correct+excluded.correct,total=total+1",(str(user_id),q["skill"],int(correct)))
            # XP and mastery are separate. Wrong answers earn no accuracy XP.
            self.db.execute("UPDATE users SET xp=xp+?,gold=gold+? WHERE user_id=?",(10 if correct else 0,3 if correct else 0,str(user_id)))
            self._activity(user_id,'quiz' if q['skill'] not in ('Lesen','Hoeren') else q['skill'].lower(),
                    '答對練習題' if correct else '練習題待複習',q['prompt']+' → '+answer,10 if correct else 0,activity_id='legacy-attempt-'+attempt_id)
        self.unlock(user_id)
        return correct,q["answer"],q["explanation"]

    def unlock(self,user_id):
        uid=str(user_id)
        count=self.db.execute("SELECT COUNT(*) FROM attempts WHERE user_id=?",(uid,)).fetchone()[0]
        with self.db:
            self.db.execute("UPDATE quests SET status='available' WHERE user_id=? AND status='locked' AND trigger_kind='attempts' AND CAST(trigger_value AS INTEGER)<=?",(uid,count))
            self.db.execute("""UPDATE quests SET status='available' WHERE user_id=? AND status='locked'
                AND trigger_kind='quest' AND EXISTS
                (SELECT 1 FROM quests prev WHERE prev.id=quests.trigger_value AND prev.user_id=quests.user_id AND prev.status='completed')""",(uid,))

    def quests(self,user_id):
        self.user(user_id);self.unlock(user_id)
        return self.db.execute("""SELECT * FROM quests WHERE user_id=? AND status IN ('available','active','locked')
            ORDER BY CASE kind WHEN 'main' THEN 0 ELSE 1 END, id""",(str(user_id),)).fetchall()

    def quest_scene(self,quest):
        qid=quest["id"]
        if qid==f"MAIN-{quest['user_id']}-01":
            return {"location":"公會圖書館 · Die Gildenbibliothek", "npc":"學者艾爾文 · Alwin",
              "opening":"雨後的石板路泛著微光。你推開公會圖書館的橡木門，學者艾爾文正在整理一本會自行翻頁的古書。",
              "greeting":"Willkommen in der Gildenbibliothek! Wie heißt du, und warum lernst du Deutsch?",
              "goal":"完成 2 道文法題，並用德文向學者介紹自己。", "minimum_quizzes":2}
        if qid==f"MAIN-{quest['user_id']}-02":
            return {"location":"公會地圖室 · Die Kartenkammer","npc":"地圖師瑪拉 · Mara",
              "opening":"城牆後的地圖室藏著一幅巨大的羊皮紙。五個領土的輪廓在燭光下緩緩浮現，瑪拉請你尋找圖書館失落的線索。",
              "greeting":"Welche Stadt im deutschsprachigen Raum möchtest du besuchen? Warum?",
              "goal":"完成 3 道文法題，再用德文告訴地圖師想去的城市與原因。", "minimum_quizzes":3}
        if qid==f"MAIN-{quest['user_id']}-03":
            return {"location":"古代檔案館 · Das alte Archiv","npc":"守門者弗里德里希 · Friedrich",
              "opening":"檔案館的鐵門已塵封多年。守門者提出最後一個問題：只有能夠解釋自己選擇的人，才有資格持有檔案之鑰。",
              "greeting":"Wem vertraust du, und warum? Erkläre deine Entscheidung auf Deutsch.",
              "goal":"完成 3 道文法題，再用德文說明你相信誰、為什麼。", "minimum_quizzes":3}
        if qid==f"SIDE-{quest['user_id']}-01":
            return {"location":"旅行者酒館 · Die Taverne","npc":"旅行者莉娜 · Lina",
              "opening":"你在酒館角落發現一封未封口的信。旅行者莉娜神色焦急，她需要用有禮貌的德文向城主求助。",
              "greeting":"Könntest du mir bitte helfen? Wie würdest du höflich um Hilfe bitten?",
              "goal":"完成 1 道文法題，並用德文向旅行者示範禮貌請求。", "minimum_quizzes":1}
        return {"location":"公會委託處 · Die Gilde","npc":"公會使者 · Bote",
          "opening":quest["description"],"greeting":"Was würdest du in dieser Situation sagen?",
          "goal":"完成 2 道文法題，再用德文回答公會使者。", "minimum_quizzes":2}

    def quest_state(self,user_id,quest_id):
        self.user(user_id);self.unlock(user_id)
        q=self.db.execute("SELECT * FROM quests WHERE id=? AND user_id=?",(quest_id,str(user_id))).fetchone()
        if not q:raise ValueError("找不到你的任務。")
        scene=self.quest_scene(q)
        progress=self.db.execute("SELECT * FROM quest_progress WHERE user_id=? AND quest_id=?",(str(user_id),quest_id)).fetchone()
        phase=progress["phase"] if progress else 0
        baseline=progress["baseline_attempts"] if progress else 0
        quiz_count=self.db.execute("SELECT COUNT(*) FROM quest_attempts WHERE user_id=? AND quest_id=?",
            (str(user_id),quest_id)).fetchone()[0] if progress else 0
        if phase==1 and quiz_count>=scene["minimum_quizzes"]:
            phase=2
            with self.db:self.db.execute("UPDATE quest_progress SET phase=2 WHERE user_id=? AND quest_id=?",(str(user_id),quest_id))
        return {"quest":q,"scene":scene,"phase":phase,"quiz_count":quiz_count}

    def start_quest(self,user_id,quest_id):
        st=self.quest_state(user_id,quest_id)
        if st["quest"]["status"]=="locked":raise ValueError("尚未解鎖這項任務。")
        if st["quest"]["status"]=="completed":raise ValueError("這項任務已完成。")
        if st["phase"]==0:
            baseline=self.db.execute("SELECT COUNT(*) FROM attempts WHERE user_id=?",(str(user_id),)).fetchone()[0]
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO quest_progress(user_id,quest_id,phase,baseline_attempts) VALUES(?,?,1,?)",(str(user_id),quest_id,baseline))
                self.db.execute("UPDATE quests SET status='active' WHERE id=? AND user_id=? AND status='available'",(quest_id,str(user_id)))
        return self.quest_state(user_id,quest_id)

    def submit_npc_answer(self,user_id,quest_id,response):
        st=self.quest_state(user_id,quest_id)
        if st["quest"]["status"]!='active' or st["phase"]!=2:
            raise ValueError("請先進入任務並完成文法試煉，再向 NPC 回話。")
        if len(response.strip().split())<3:raise ValueError("請至少寫出三個德文詞語，完整回覆 NPC。")
        rid=self.add_record(user_id,"free_answer",response,prompt=st["scene"]["greeting"],source=f"quest:{quest_id}")
        with self.db:
            self.db.execute("UPDATE quest_progress SET phase=3,npc_record_id=? WHERE user_id=? AND quest_id=?",(rid,str(user_id),quest_id))
        return rid

    def finish_quest(self,user_id,quest_id):
        st=self.quest_state(user_id,quest_id)
        q=st["quest"]
        if q["status"]!='active' or st["phase"]!=3:
            raise ValueError("尚未完成任務：請先開始冒險、完成文法題並回答 NPC。")
        with self.db:
            self.db.execute("UPDATE quests SET status='completed' WHERE id=? AND user_id=?",(quest_id,str(user_id)))
            self.db.execute("UPDATE users SET xp=xp+?,gold=gold+? WHERE user_id=?",(q["xp"],q["gold"],str(user_id)))
            if q["kind"]=="main":
                self.db.execute("UPDATE users SET chapter=chapter+1 WHERE user_id=?",(str(user_id),))
            self._activity(user_id,'quest','完成主線' if q['kind']=='main' else '完成支線',q['title'],q['xp'])
        self.unlock(user_id)
        return q

    def set_reminder(self,user_id,enabled):
        self.user(user_id)
        with self.db:self.db.execute("UPDATE reminder_preferences SET enabled=? WHERE user_id=?",(int(bool(enabled)),str(user_id)))

    def reminder_enabled(self,user_id):
        self.user(user_id)
        return bool(self.db.execute("SELECT enabled FROM reminder_preferences WHERE user_id=?",(str(user_id),)).fetchone()[0])

    @staticmethod
    def latest_reminder_cutoff(reference=None):
        t=reference or datetime.now(TZ)
        t=t.astimezone(TZ)
        # Sunday=6 (Monday=0); weekly deadline: Sunday 20:00 Taipei time.
        sunday=(t-timedelta(days=(t.weekday()+1)%7)).replace(hour=20,minute=0,second=0,microsecond=0)
        return sunday if t>=sunday else sunday-timedelta(days=7)

    def due_reminder_users(self,reference=None):
        cutoff=self.latest_reminder_cutoff(reference)
        # Avoid retroactive pings for newly created records after Sunday cutoff.
        rows=self.db.execute("""SELECT p.user_id,COUNT(r.id) AS n FROM reminder_preferences p
            JOIN records r ON r.user_id=p.user_id AND r.kind IN ('diary','free_answer')
                AND r.status IN ('pending','exported') AND r.created_at<=?
            WHERE p.enabled=1 AND NOT EXISTS(SELECT 1 FROM reminder_deliveries d
                WHERE d.user_id=p.user_id AND d.cutoff_date=?) GROUP BY p.user_id""",
            (cutoff.isoformat(timespec="seconds"),cutoff.date().isoformat())).fetchall()
        return [(r["user_id"],int(r["n"]),cutoff.date().isoformat()) for r in rows]

    def mark_reminder(self,user_id,cutoff_date,result):
        with self.db:self.db.execute("INSERT OR IGNORE INTO reminder_deliveries VALUES(?,?,?,?)",(str(user_id),cutoff_date,result,now()))

    def reminder_banner(self,user_id,reference=None):
        self.user(user_id)
        cutoff=self.latest_reminder_cutoff(reference)
        n=self.db.execute("""SELECT COUNT(*) FROM records WHERE user_id=? AND kind IN ('diary','free_answer')
            AND status IN ('pending','exported') AND created_at<=?""",(str(user_id),cutoff.isoformat(timespec="seconds"))).fetchone()[0]
        return f"📣 週批改提醒：有 {n} 筆舊日記／NPC 回答尚待 GPT 分析！使用 /de review status 或 export。" if n else None

    def profile(self,user_id):
        u=self.user(user_id)
        level=1+u["xp"]//100
        rank=max((name for minimum,name in RANKS if level>=minimum),key=lambda name:next(minimum for minimum,n in RANKS if n==name))
        skills=self.db.execute("SELECT * FROM skills WHERE user_id=? ORDER BY total DESC",(str(user_id),)).fetchall()
        pending=self.db.execute("SELECT COUNT(*) FROM records WHERE user_id=? AND status!='reviewed'",(str(user_id),)).fetchone()[0]
        return {"level":level,"rank":rank,"xp":u["xp"],"gold":u["gold"],"chapter":u["chapter"],"skills":[dict(x) for x in skills],"pending":pending}

    def culture(self,user_id,category=None):
        self.user(user_id)
        rows=self.db.execute("SELECT n.*,COALESCE(p.state,0) state FROM culture_nodes n LEFT JOIN culture_progress p ON p.node_id=n.id AND p.user_id=? ORDER BY n.category,n.id",(str(user_id),)).fetchall()
        return [dict(r) for r in rows if not category or r["category"]==category]

    def culture_discover(self,user_id,node_id):
        self.user(user_id)
        if not self.db.execute("SELECT 1 FROM culture_nodes WHERE id=?",(node_id,)).fetchone():raise ValueError("文化節點不存在。")
        with self.db:
            self.db.execute("INSERT INTO culture_progress(user_id,node_id,state) VALUES(?,?,1) ON CONFLICT(user_id,node_id) DO UPDATE SET state=MAX(state,1)",(str(user_id),node_id))
            self._activity(user_id,'culture','發現文化知識',node_id)

    def export(self,user_id):
        self.user(user_id)
        batch="DE-"+uuid.uuid4().hex[:16]
        records=[dict(r) for r in self.db.execute("SELECT id,kind,prompt,response,source,created_at FROM records WHERE user_id=? AND status='pending' ORDER BY created_at",(str(user_id),))]
        vocab=[dict(r) for r in self.db.execute("SELECT id,term,source,note,created_at FROM vocab WHERE user_id=? ORDER BY created_at DESC LIMIT 200",(str(user_id),))]
        payload={"schema_version":"1.0","batch_id":batch,"user_id":str(user_id),"exported_at":now(),"timezone":"Asia/Taipei","learner":{"cefr_level":"A2-B1","target_level":"B2","focus":["active_vocabulary","articles","verb_conjugation"]},"records":records,"vocabulary":vocab,"vocabulary_review":[dict(r) for r in self.db.execute("SELECT * FROM vocab_review WHERE user_id=?",(str(user_id),))],"skill_summary":self.profile(user_id)["skills"],"quiz_progress":[dict(r) for r in self.db.execute("SELECT * FROM quiz_progress WHERE user_id=?",(str(user_id),))],"culture_progress":self.culture(user_id),"rpg_state":{"profile":{k:v for k,v in self.profile(user_id).items() if k not in ("skills",)},"quests":[dict(q) for q in self.quests(user_id)]},"review_instructions":"Correct each record by ID, preserve batch_id and user_id. Generate a reasonable number of validated multiple-choice questions and quests. Return DE-Learn Exchange v1 JSON. Never invent record IDs or award XP directly."}
        with self.db:
            self.db.execute("INSERT INTO exports VALUES(?,?,?,?)",(batch,str(user_id),now(),dumps(payload)))
            self.db.executemany("UPDATE records SET status='exported',batch_id=? WHERE id=?",[(batch,r["id"]) for r in records])
        return payload

    def resend_export(self,user_id,batch_id=None):
        self.user(user_id)
        if batch_id:
            row=self.db.execute("SELECT * FROM exports WHERE user_id=? AND batch_id=?",(str(user_id),batch_id)).fetchone()
        else:
            row=self.db.execute("""SELECT e.* FROM exports e WHERE e.user_id=?
                AND EXISTS (SELECT 1 FROM records r WHERE r.user_id=e.user_id AND r.batch_id=e.batch_id AND r.status='exported')
                ORDER BY e.created_at DESC LIMIT 1""",(str(user_id),)).fetchone()
        if not row:raise ValueError("沒有找到仍待批改的匯出批次；請使用 /de review export。")
        return json.loads(row["payload"])

    def import_preview(self,user_id,payload):
        if not isinstance(payload,dict) or payload.get("schema_version")!="1.0":raise ValueError("不支援的 JSON schema_version。")
        batch=payload.get("batch_id")
        if not isinstance(batch,str):raise ValueError("缺少 batch_id。")
        exp=self.db.execute("SELECT * FROM exports WHERE batch_id=? AND user_id=?",(batch,str(user_id))).fetchone()
        if not exp:raise ValueError("找不到對應的匯出批次，或使用者不符。")
        if str(payload.get("user_id"))!=str(user_id):raise ValueError("user_id 不符。")
        if self.db.execute("SELECT 1 FROM packages WHERE batch_id=?",(batch,)).fetchone():raise ValueError("此批次已匯入過。")
        corrections=payload.get("corrections",[]);questions=payload.get("questions",[]);quests=payload.get("quests",[]);culture=payload.get("culture_updates",[])
        for name,items,limit in (("corrections",corrections,500),("questions",questions,200),("quests",quests,40),("culture_updates",culture,100)):
            if not isinstance(items,list) or len(items)>limit:raise ValueError(f"{name} 必須是陣列且不得超過 {limit} 筆。")
        if not any((corrections,questions,quests,culture)):raise ValueError("空白批改檔，沒有可匯入內容。")
        expected={r["id"] for r in json.loads(exp["payload"])["records"]}
        seen=set()
        for c in corrections:
            if not isinstance(c,dict) or c.get("record_id") not in expected or c["record_id"] in seen:raise ValueError("批改 ID 不屬於這個批次或重複。")
            seen.add(c["record_id"])
            if c.get("status") not in ("correct","incorrect","uncertain"):raise ValueError("無效批改狀態。")
            if not isinstance(c.get("errors",[]),list):raise ValueError("errors 必須是陣列。")
            for error in c.get("errors",[]):
                if not isinstance(error,dict) or error.get("category") not in SKILLS:raise ValueError("未知的文法技能分類。")
        ids=set()
        for q in questions:
            if not isinstance(q,dict) or not isinstance(q.get("question_id"),str) or q["question_id"] in ids:raise ValueError("題目 ID 缺失或重複。")
            ids.add(q["question_id"])
            if q.get("type")!="multiple_choice" or q.get("skill") not in SKILLS:raise ValueError("V1 僅支援合法技能的 multiple_choice。")
            if not isinstance(q.get("options"),list) or len(q["options"])<2 or len(q["options"])>5 or not all(isinstance(o,str) and o.strip() for o in q["options"]):raise ValueError("選項格式錯誤。")
            normalized_options=[self._normalized_answer(option) for option in q["options"]]
            if len(normalized_options)!=len(set(normalized_options)):raise ValueError("題目包含重複選項，請修正後再匯入。")
            if not isinstance(q.get("answer"),str) or self._normalized_answer(q["answer"]) not in normalized_options:raise ValueError("標準答案不在選項中。")
            if not isinstance(q.get("question"),str) or len(q["question"])>1000:raise ValueError("題目文字錯誤。")
            if q['skill'] in ('Lesen','Hoeren'):
                if not isinstance(q.get('passage'),str) or not 20<=len(q['passage'])<=1000:
                    raise ValueError('聽讀題需要 20–1000 字元的 passage 原文。')
            if self.db.execute("SELECT 1 FROM questions WHERE id=?",(q["question_id"],)).fetchone():raise ValueError("題目 ID 已存在。")
        quest_ids=set()
        for q in quests:
            if not isinstance(q,dict) or not isinstance(q.get("quest_id"),str) or q["quest_id"] in quest_ids:raise ValueError("任務 ID 缺失或重複。")
            quest_ids.add(q["quest_id"])
            if q.get("kind") not in ("main","side") or q.get("skill") not in SKILLS:raise ValueError("無效任務類型或技能。")
            if q.get("trigger_kind","available") not in ("available","attempts"):raise ValueError("無效觸發條件。")
            if not isinstance(q.get("title"),str) or not isinstance(q.get("description"),str):raise ValueError("任務文字無效。")
            if self.db.execute("SELECT 1 FROM quests WHERE id=?",(q["quest_id"],)).fetchone():raise ValueError("任務 ID 已存在。")
        for u in culture:
            if not isinstance(u,dict) or u.get("state") not in (1,2,3) or not self.db.execute("SELECT 1 FROM culture_nodes WHERE id=?",(u.get("node_id"),)).fetchone():raise ValueError("文化節點或狀態無效。")
        return {"batch_id":batch,"corrections":len(corrections),"questions":len(questions),"quests":len(quests),"culture_updates":len(culture),"unreviewed":len(expected-seen)}

    def import_apply(self,user_id,payload):
        info=self.import_preview(user_id,payload)
        batch=info["batch_id"]
        digest=hashlib.sha256(dumps(payload).encode()).hexdigest()
        with self.db:
            for c in payload.get("corrections",[]):
                rid=c["record_id"]
                errors=c.get("errors",[])
                self.db.execute("INSERT INTO corrections VALUES(?,?,?,?,?,?,?,?)",(rid,str(user_id),c["status"],c.get("corrected"),dumps(errors),c.get("explanation_zh",""),c.get("confidence","unknown"),now()))
                self.db.execute("UPDATE records SET status='reviewed' WHERE id=? AND user_id=?",(rid,str(user_id)))
                if c["status"]=="incorrect":
                    for error in errors:
                        skill=error["category"]
                        self.db.execute("INSERT OR IGNORE INTO review_items(id,user_id,source_id,skill,due_at) VALUES(?,?,?,?,?)",("REV-"+uuid.uuid4().hex[:12],str(user_id),rid,skill,(datetime.now(TZ)+timedelta(days=1)).isoformat(timespec="seconds")))
            for q in payload.get("questions",[]):
                self.db.execute("INSERT INTO questions(id,type,skill,prompt,options,answer,explanation,level,owner_id,package_id) VALUES(?,?,?,?,?,?,?,?,?,?)",(q["question_id"],q["type"],q["skill"],q["question"],dumps(q["options"]),q["answer"],q.get("explanation_zh",""),q.get("level","A2-B1"),str(user_id),batch))
                if q['skill'] in ('Lesen','Hoeren'):
                    self.db.execute("INSERT INTO media_passages VALUES(?,?,?)",
                        (q['question_id'],q['passage'],q['skill']))
            for q in payload.get("quests",[]):
                trigger=q.get("trigger_kind","available")
                self.db.execute("INSERT INTO quests(id,user_id,kind,title,description,skill,trigger_kind,trigger_value,status,xp,gold,package_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(q["quest_id"],str(user_id),q["kind"],q["title"][:120],q["description"][:1500],q["skill"],trigger,str(q.get("trigger_value","")),"available" if trigger=="available" else "locked",min(100,max(0,int(q.get("xp",30)))),min(50,max(0,int(q.get("gold",10)))),batch))
            for u in payload.get("culture_updates",[]):
                self.db.execute("INSERT INTO culture_progress(user_id,node_id,state) VALUES(?,?,?) ON CONFLICT(user_id,node_id) DO UPDATE SET state=MAX(state,excluded.state)",(str(user_id),u["node_id"],u["state"]))
            self.db.execute("INSERT INTO packages VALUES(?,?,?,?)",(batch,str(user_id),digest,now()))
            self._activity(user_id,'review','匯入每週 GPT 分析',batch)
        return info

    def pending_reviews(self,user_id):
        self.user(user_id)
        return self.db.execute("SELECT r.id,c.errors,c.corrected FROM review_items rv JOIN records r ON r.id=rv.source_id LEFT JOIN corrections c ON c.record_id=r.id WHERE rv.user_id=? AND rv.due_at<=? ORDER BY rv.due_at LIMIT 10",(str(user_id),now())).fetchall()
