"""Discord slash commands for the API-free German-learning RPG."""
import asyncio
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from engine import CULTURES, SKILLS, Engine, progress_bar
from local_tts import synthesize_german
from runtime_config import session_duration_seconds
from streak_chart import render_streak_png
from sync_store import MAX_BACKUP_BYTES, SyncError, SyncStore

load_dotenv()
TOKEN=os.getenv("DISCORD_TOKEN","")
DB=Engine(os.getenv("DATABASE_PATH","data/sprachchroniken.sqlite3"))
SYNC=SyncStore(DB.db,DB.path,os.getenv("SYNC_DEVICE_LABEL","Windows" if sys.platform=="win32" else "Railway"))
OWNER_ID=os.getenv("BOT_OWNER_ID", "").strip()
AUTO_SHUTDOWN_SECONDS=session_duration_seconds(os.getenv("AUTO_SHUTDOWN_HOURS", "0"))
LISTENING_ENABLED=(sys.platform == "win32" and os.getenv("ENABLE_LISTENING", "true").lower() in ("1", "true", "yes", "on"))

intents=discord.Intents.default()
bot=commands.Bot(command_prefix="!unused",intents=intents)
de=app_commands.Group(name="de",description="Die Sprachchroniken 德文冒險")
vocab_group=app_commands.Group(name="vocab",description="收藏單字",parent=de)
review_group=app_commands.Group(name="review",description="ChatGPT 週批改交換",parent=de)
sync_group=app_commands.Group(name="sync",description="本機與雲端的完整資料庫備份和還原",parent=de)
culture_group=app_commands.Group(name="culture",description="探索五大文化領土",parent=de)
PENDING_SYNC_IMPORTS={}


def uid(interaction):return str(interaction.user.id)


async def say(interaction,text,ephemeral=True):
    await interaction.response.send_message(text[:1950],ephemeral=ephemeral)


class OwnedView(discord.ui.View):
    """Keep one player's private RPG controls from being used by others."""
    def __init__(self, owner_id:int, timeout:float=300):
        super().__init__(timeout=timeout)
        self.owner_id=owner_id

    async def interaction_check(self, interaction:discord.Interaction) -> bool:
        if interaction.user.id!=self.owner_id:
            await interaction.response.send_message("這是其他冒險者的操作介面，請使用 `/de daily` 開啟自己的任務。",ephemeral=True)
            return False
        return True


class DiaryModal(discord.ui.Modal,title="📖 冒險者日誌"):
    entry=discord.ui.TextInput(label="今天想記錄的德文",style=discord.TextStyle.paragraph,placeholder="Heute habe ich...",max_length=1500,required=True)

    async def on_submit(self,interaction:discord.Interaction):
        try:rid=DB.add_record(uid(interaction),"diary",str(self.entry))
        except ValueError as e:return await say(interaction,str(e))
        await interaction.response.send_message(f"📖 已收藏日記 `{rid}`！你可以從『今日足跡』重新查看原文，週末再交 ChatGPT 批改。",
            view=BackView(interaction.user.id),ephemeral=True)


class VocabModal(discord.ui.Modal,title="🌿 收藏德文單字"):
    term=discord.ui.TextInput(label="德文單字或片語",placeholder="die Vorsorgeuntersuchung",max_length=150)
    source=discord.ui.TextInput(label="來源（可留空）",placeholder="Netflix / 雜誌 / 朋友",required=False,max_length=100)
    note=discord.ui.TextInput(label="自己的筆記（可留空）",style=discord.TextStyle.paragraph,required=False,max_length=500)

    async def on_submit(self,interaction:discord.Interaction):
        try:vid=DB.add_vocab(uid(interaction),str(self.term),str(self.source) or "personal",str(self.note))
        except ValueError as e:return await say(interaction,str(e))
        await interaction.response.send_message(
            f"🌿 {'已收藏：'+str(self.term) if vid else '這個詞已經收藏過了：'+str(self.term)}。\n可從『單字回想』反覆練習。",
            view=BackView(interaction.user.id),ephemeral=True)


def quiz_embed(q):
    options=json.loads(q["options"])
    media=DB.media(q["id"])
    if media and media['mode']=='Lesen':
        title="📖 閱讀探索｜Lesen"
        description=f"**閱讀短文：**\n{media['passage']}\n\n**Frage:** {q['prompt']}"
    elif media and media['mode']=='Hoeren':
        title="🎧 聽力探索｜Hören"
        description=f"**請先聽附件的德語音檔，不要先看逐字稿。**\n\n**Frage:** {q['prompt']}"
    else:
        title="⚔️ 文法挑戰"
        description=q['prompt']
    embed=discord.Embed(title=title,description=description,color=discord.Color.blurple())
    embed.add_field(name="技能",value=q["skill"],inline=True)
    embed.add_field(name="程度",value=q["level"] or "A2–B1",inline=True)
    embed.add_field(name="選項",value="\n".join(f"**{i+1}.** {o}" for i,o in enumerate(options)),inline=False)
    embed.set_footer(text="點選答案即可批改：答對 +10 XP，答錯 +0 XP；同題依複習排程再出現。")
    return embed


async def send_quiz(interaction,q,quest_id=None,edit=False):
    """Present quiz; prepare Windows local audio without hitting Discord's 3s interaction timeout."""
    audio_path=None
    media=DB.media(q['id'])
    if media and media['mode']=='Hoeren':
        # Component clicks should update the current message; slash commands reply privately.
        await interaction.response.defer(thinking=not edit,ephemeral=True)
        try:
            audio_path=await asyncio.to_thread(synthesize_german,media['passage'])
            kwargs={'embed':quiz_embed(q),'view':QuizView(interaction.user.id,q,quest_id)}
            audio=discord.File(str(audio_path),filename='hoeren.wav')
            try:
                if edit:
                    await interaction.edit_original_response(**kwargs,content=None,attachments=[audio])
                else:
                    await interaction.followup.send(**kwargs,file=audio,ephemeral=True)
            finally:
                audio.close()
        except RuntimeError as exc:
            msg=f"🎧 {exc}\n你仍然可以使用『閱讀探索』練習。"
            if edit:
                await interaction.edit_original_response(content=msg,embed=None,view=BackView(interaction.user.id),attachments=[])
            else:
                await interaction.followup.send(msg,ephemeral=True)
        finally:
            if audio_path:audio_path.unlink(missing_ok=True)
        return
    kwargs={'embed':quiz_embed(q),'view':QuizView(interaction.user.id,q,quest_id)}
    if edit:await interaction.response.edit_message(**kwargs,content=None,attachments=[])
    else:await interaction.response.send_message(**kwargs,ephemeral=True)


class QuizView(OwnedView):
    def __init__(self, owner_id:int, question, quest_id=None):
        super().__init__(owner_id,timeout=300)
        self.question_id=question["id"]
        self.quest_id=quest_id
        self.mode_skill=question['skill'] if question['skill'] in ('Lesen','Hoeren') else None
        self.answered=False
        for index,option in enumerate(json.loads(question["options"])):
            button=discord.ui.Button(label=f"{index+1}. {option}"[:80],style=discord.ButtonStyle.secondary,row=index//5)

            # Factory binds each button's index independently, avoiding closure/option mix-ups.
            def make_callback(choice_index:int):
                async def on_answer(interaction:discord.Interaction):
                    if self.answered:
                        return await interaction.response.send_message("這道題已作答，請開始下一題。",ephemeral=True)
                    self.answered=True
                    try:
                        correct,expected,explanation,selected=DB.answer_choice(uid(interaction),self.question_id,choice_index,quest_id=self.quest_id)
                    except ValueError as exc:
                        self.answered=False
                        return await interaction.response.send_message(str(exc),ephemeral=True)
                    self.stop()
                    reward=10 if correct else 0
                    title="✅ 答對了！" if correct else "❌ 答錯了！"
                    media=DB.media(self.question_id)
                    comparison=(f"**你的選擇：{selected}**\n"
                                f"**標準答案：{expected}**\n\n"
                                f"**說明：** {explanation or '無'}\n\n"
                                f"**本題獎勵：+{reward} XP**")
                    if media and media['mode']=='Hoeren':
                        comparison+=f"\n\n**聽力逐字稿：**\n{media['passage']}"
                    result=discord.Embed(title=title,description=comparison,
                                         color=discord.Color.green() if correct else discord.Color.red())
                    result.set_footer(text="這題已記錄；答錯會計入練習統計，但不算答對。")
                    await interaction.response.edit_message(embed=result,view=QuizResultView(interaction.user.id,self.question_id,self.quest_id,self.mode_skill))
                return on_answer

            button.callback=make_callback(index)
            self.add_item(button)


class QuizResultView(OwnedView):
    """Post-answer navigation; no need to type a slash command."""
    def __init__(self,owner_id:int,previous_question_id:str,quest_id=None,mode_skill=None):
        super().__init__(owner_id)
        self.previous_question_id=previous_question_id
        self.quest_id=quest_id
        self.mode_skill=mode_skill
        if not quest_id:
            self.remove_item(self.go_quest)

    @discord.ui.button(label="➡️ 下一題",style=discord.ButtonStyle.success,row=0)
    async def next_question(self,interaction:discord.Interaction,button:discord.ui.Button):
        if self.quest_id:
            st=DB.quest_state(uid(interaction),self.quest_id)
            if st["phase"]>=2:
                self.stop()
                return await interaction.response.edit_message(embed=quest_detail_embed(uid(interaction),self.quest_id),view=QuestDetailView(interaction.user.id,self.quest_id))
        q=DB.get_question(uid(interaction),skill=st["quest"]["skill"] if self.quest_id else self.mode_skill,
                          exclude_id=self.previous_question_id)
        if not q and self.quest_id:
            q=DB.get_question(uid(interaction),exclude_id=self.previous_question_id)
        if not q:
            summary=DB.quiz_overview(uid(interaction),self.mode_skill)
            msg=f"新題 {summary['new']}｜到期複習 {summary['due']}｜尚未到期 {summary['waiting']}。"
            return await interaction.response.send_message("🎉 目前沒有可練的題目！"+msg+" 下次到期時再挑戰，或等待每週匯入新題。",ephemeral=True)
        self.stop()
        await send_quiz(interaction,q,self.quest_id,edit=True)

    @discord.ui.button(label="📜 查看任務進度",style=discord.ButtonStyle.secondary,row=1)
    async def go_quest(self,interaction:discord.Interaction,button:discord.ui.Button):
        if not self.quest_id:
            return await interaction.response.send_message("這題不是從任務開始的，請使用公會任務按鈕。",ephemeral=True)
        self.stop()
        await interaction.response.edit_message(embed=quest_detail_embed(uid(interaction),self.quest_id),view=QuestDetailView(interaction.user.id,self.quest_id))

    @discord.ui.button(label="🏠 返回冒險首頁",style=discord.ButtonStyle.primary,row=0)
    async def go_home(self,interaction:discord.Interaction,button:discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id))


def home_embed(user_id):
    ov=DB.overview(user_id);p=ov['profile'];streak=DB.streak_stats(user_id)
    xp_level=p['xp']%100
    e=discord.Embed(title="🌞 Die Sprachchroniken — 今日冒險",
        description=f"歡迎回到公會！\n\n**角色等級 Lv.{p['level']}** `{progress_bar(xp_level,100)}` {xp_level}/100 XP\n"
                    f"**V1 世界開拓度** `{progress_bar(ov['overall'],100)}` **{ov['overall']}%**",
        color=discord.Color.gold())
    e.add_field(name="冒險者",value=f"**{p['rank']}** · 🪙 {p['gold']} Gold",inline=True)
    e.add_field(name="今日足跡",value=f"📜 {ov['today']['events']} 件學習事件｜✨ +{ov['today']['xp']} XP",inline=True)
    e.add_field(name="開拓戰況",value=f"📜 主線 {ov['main_done']}/{ov['main_total']}｜🗺️ 文化 {ov['culture_discovered']}/{ov['culture_total']}\n"
                f"⚔️ 題庫接觸 {ov['quiz_seen']}/{ov['quiz_total']}｜🌿 收藏 {ov['vocab_total']} 詞",inline=False)
    quiz=DB.quiz_overview(user_id)
    e.add_field(name="🧠 文法題進度",value=f"新題 {quiz['new']}｜到期複習 {quiz['due']}｜尚未到期 {quiz['waiting']}",inline=False)
    e.add_field(name="🔥 學習連續天數",value=f"目前 **{streak.current_streak} 天**｜歷史最佳 **{streak.max_streak} 天**｜近一年活躍 **{streak.active_days} 天**\n使用 `/de streak` 查看完整熱力圖。",inline=False)
    reminder=DB.reminder_banner(user_id)
    if reminder:e.add_field(name="🔔 每週日記提醒",value=reminder,inline=False)
    e.set_footer(text=f"待 GPT 批改：{p['pending']} 筆｜週日 20:00 台灣時間｜開拓度只代表目前 V1 內容，不是德語程度")
    return e


def overview_embed(user_id):
    d=DB.overview(user_id); p=d['profile']; streak=DB.streak_stats(user_id)
    embed=discord.Embed(title="🏆 帝國開拓總覽",description=(
        f"**Lv.{p['level']} {p['rank']}**  ✨ {p['xp']} XP\n"
        f"等級：`{progress_bar(p['xp']%100,100,18)}` {p['xp']%100}/100\n\n"
        f"**V1 可開拓內容：{d['overall']}%**\n"
        f"`{progress_bar(d['overall'],100,18)}`\n"
        f"📜 主線：`{progress_bar(d['main_done'],d['main_total'])}` {d['main_done']}/{d['main_total']}\n"
        f"⚔️ 文法題接觸：`{progress_bar(d['quiz_seen'],d['quiz_total'])}` {d['quiz_seen']}/{d['quiz_total']}\n"
        f"🗺️ 文化發現：`{progress_bar(d['culture_discovered'],d['culture_total'])}` {d['culture_discovered']}/{d['culture_total']}\n"
        f"⭐ 文化掌握：`{progress_bar(d['culture_mastered'],d['culture_total'])}` {d['culture_mastered']}/{d['culture_total']}\n"
        f"🌿 個人詞庫 {d['vocab_total']} 個｜連續兩次回想成功 {d['vocab_recalled']} 個"),color=discord.Color.gold())
    cats=DB.culture(user_id)
    for category in sorted(CULTURES):
        entries=[v for v in cats if v['category']==category]
        discovered=sum(v['state']>0 for v in entries)
        embed.add_field(name=category,value=f"`{progress_bar(discovered,len(entries))}` {discovered}/{len(entries)}",inline=False)
    embed.add_field(name="🔥 學習 Streak",value=f"目前 **{streak.current_streak} 天**｜最佳 **{streak.max_streak} 天**｜活躍 **{streak.active_days}/365 天**\n`/de streak` 開啟學習日曆",inline=False)
    embed.set_footer(text="世界開拓度 = 主線完成、文法題接觸、文化探索平均；各自有獨立指標，不代表 CEFR。")
    return embed


async def show_streak(interaction,edit=False):
    stats=DB.streak_stats(uid(interaction))
    payload=await asyncio.to_thread(render_streak_png,stats)
    filename="sprachchroniken_streak.png"
    embed=discord.Embed(title="🔥 學習連續紀錄｜Lernkalender",
        description=(f"**目前連續：{stats.current_streak} 天**｜歷史最佳：{stats.max_streak} 天\n"
                     f"近 365 天活躍：**{stats.active_days} 天**｜學習行動：{stats.total_actions} 次\n"
                     "完成答題、寫日記、收藏單字、回想單字、任務或文化探索等，當天就會亮起一格。"),
        color=discord.Color.green())
    embed.set_image(url=f"attachment://{filename}")
    embed.set_footer(text="使用台灣日期計算；今天尚未學習時，昨天的連續紀錄仍暫時保留。此圖只讀取資料，不會增加 XP。")
    uploaded=discord.File(io.BytesIO(payload),filename=filename)
    try:
        if edit:
            await interaction.response.edit_message(content=None,embed=embed,
                view=BackView(interaction.user.id),attachments=[uploaded])
        else:
            await interaction.response.send_message(embed=embed,file=uploaded,
                view=BackView(interaction.user.id),ephemeral=True)
    finally:
        uploaded.close()


def journal_embed(user_id,day=None):
    stats=DB.activity_summary(user_id,day);logs=DB.activity(user_id,day=day,limit=15)
    labels={'quiz':'文法練習','lesen':'閱讀','hoeren':'聽力','vocab':'收藏單字','vocab_review':'單字回想',
            'diary':'日記','collection':'收藏句子','free_answer':'NPC 回答','quest':'公會任務','culture':'文化發現','review':'GPT 批改'}
    counts='｜'.join(f"{labels.get(k,k)} {v}" for k,v in sorted(stats['kinds'].items()))
    embed=discord.Embed(title=f"📜 冒險者日誌｜{stats['day']}",description=(
        f"**今日累積 {stats['events']} 次行動 · +{stats['xp']} XP**\n"
        f"{counts or '今天還沒有學習紀錄'}\n\n"
        "**最近活動（個人可見）**"),color=discord.Color.teal())
    if logs:
        lines=[f"`{row['created_at'][11:16]}` {'✅' if row['xp_delta'] else '📌'} **{row['title']}**"
               f"｜{row['detail'][:85]}{'…' if len(row['detail'])>85 else ''}" for row in logs]
        # Discord embed description max 4096; truncate conservatively.
        embed.description+='\n'+'\n'.join(lines)[:2900]
    embed.set_footer(text="原文保存在本機 SQLite；此頁僅自己可見。分享只會發送統計，不公開日記內容。")
    return embed


class HomeView(OwnedView):
    def __init__(self,owner_id:int):
        super().__init__(owner_id)
        if not LISTENING_ENABLED:
            for item in list(self.children):
                if isinstance(item,discord.ui.Button) and item.label=="🎧 聽力探索":
                    self.remove_item(item)

    @discord.ui.button(label="⚔️ 文法挑戰",style=discord.ButtonStyle.primary,row=0)
    async def practice_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        q=DB.get_question(uid(interaction))
        if not q:return await interaction.response.send_message("題庫暫無選擇題。",ephemeral=True)
        await interaction.response.edit_message(embed=quiz_embed(q),view=QuizView(interaction.user.id,q))

    @discord.ui.button(label="📖 寫日記",style=discord.ButtonStyle.success,row=0)
    async def diary_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.send_modal(DiaryModal())

    @discord.ui.button(label="🌿 收藏單字",style=discord.ButtonStyle.secondary,row=0)
    async def vocab_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.send_modal(VocabModal())

    @discord.ui.button(label="🏰 公會任務",style=discord.ButtonStyle.secondary,row=1)
    async def quest_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=quest_board_embed(uid(interaction)),view=QuestBoardView(interaction.user.id))

    @discord.ui.button(label="🗺️ 文化領土",style=discord.ButtonStyle.secondary,row=1)
    async def culture_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        rows=DB.culture(uid(interaction))
        lines=[]
        for category in sorted(CULTURES):
            nodes=[r for r in rows if r["category"]==category]
            discovered=sum(r["state"]>=1 for r in nodes)
            mastered=sum(r["state"]==3 for r in nodes)
            lines.append(f"**{category}** ` {progress_bar(discovered,len(nodes))} ` 探索 {discovered}/{len(nodes)}｜掌握 {mastered}/{len(nodes)}")
        embed=discord.Embed(title="🗺️ 文化探索地圖",description="\n".join(lines),color=discord.Color.green())
        await interaction.response.edit_message(embed=embed,view=BackView(interaction.user.id))


    @discord.ui.button(label="🌿 單字回想",style=discord.ButtonStyle.success,row=2)
    async def vocab_review_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await show_vocab_review(interaction,edit=True)

    @discord.ui.button(label="📖 閱讀探索",style=discord.ButtonStyle.secondary,row=2)
    async def lesen_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await start_media(interaction,"Lesen",edit=True)

    @discord.ui.button(label="🎧 聽力探索",style=discord.ButtonStyle.secondary,row=2)
    async def hoeren_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await start_media(interaction,"Hoeren",edit=True)

    @discord.ui.button(label="📜 今日足跡",style=discord.ButtonStyle.secondary,row=3)
    async def journal_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=journal_embed(uid(interaction)),view=JournalView(interaction.user.id))

    @discord.ui.button(label="🏆 開拓總覽",style=discord.ButtonStyle.primary,row=3)
    async def overview_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=overview_embed(uid(interaction)),view=BackView(interaction.user.id))

    @discord.ui.button(label="🔥 學習日曆",style=discord.ButtonStyle.success,row=3)
    async def streak_button(self,interaction:discord.Interaction,button:discord.ui.Button):
        await show_streak(interaction,edit=True)


class JournalView(OwnedView):
    def __init__(self,owner_id,day=None):
        super().__init__(owner_id)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.day=day or datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()

    @discord.ui.button(label="⬅️ 前一天",style=discord.ButtonStyle.secondary,row=0)
    async def previous(self,interaction:discord.Interaction,button:discord.ui.Button):
        from datetime import date,timedelta
        day=(date.fromisoformat(self.day)-timedelta(days=1)).isoformat()
        await interaction.response.edit_message(embed=journal_embed(uid(interaction),day),view=JournalView(interaction.user.id,day))

    @discord.ui.button(label="➡️ 後一天",style=discord.ButtonStyle.secondary,row=0)
    async def following(self,interaction:discord.Interaction,button:discord.ui.Button):
        from datetime import date,timedelta
        from zoneinfo import ZoneInfo
        from datetime import datetime
        day=(date.fromisoformat(self.day)+timedelta(days=1)).isoformat()
        if day>datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat():
            return await interaction.response.send_message("不能跳到未來日期。",ephemeral=True)
        await interaction.response.edit_message(embed=journal_embed(uid(interaction),day),view=JournalView(interaction.user.id,day))

    @discord.ui.button(label="📄 下載當日完整紀錄",style=discord.ButtonStyle.primary,row=1)
    async def download(self,interaction:discord.Interaction,button:discord.ui.Button):
        records=DB.activity(uid(interaction),day=self.day,limit=10000)
        txt='\n'.join(f"[{r['created_at']}] {r['title']} (+{r['xp_delta']} XP)\n{r['detail']}\n" for r in reversed(records)) or '這天沒有學習紀錄。'
        payload=txt.encode('utf-8')
        await interaction.response.send_message(
            f"📄 {self.day} 的完整學習紀錄（只傳給你）",
            file=discord.File(io.BytesIO(payload),filename=f'de_journal_{self.day}.txt'),ephemeral=True)

    @discord.ui.button(label="📢 分享今日成就",style=discord.ButtonStyle.success,row=1)
    async def share(self,interaction:discord.Interaction,button:discord.ui.Button):
        stats=DB.activity_summary(uid(interaction),self.day)
        if interaction.guild is None:
            return await interaction.response.send_message("分享功能請在伺服器頻道中使用；私人日記不會被公開。",ephemeral=True)
        await interaction.response.send_message(
            f"🏆 **{interaction.user.display_name} 的德文冒險足跡｜{stats['day']}**\n"
            f"今天完成 **{stats['events']}** 件學習行動，獲得 **+{stats['xp']} XP**！\n"
            "📚 Die Sprachchroniken — 繼續前進！",ephemeral=False)

    @discord.ui.button(label="🏠 返回冒險首頁",style=discord.ButtonStyle.primary,row=2)
    async def home(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id))


class VocabAnswerModal(discord.ui.Modal,title="🌿 單字主動回想"):
    answer=discord.ui.TextInput(label="根據提示寫出完整德文（包含 Artikel）",max_length=150,required=True)

    def __init__(self,vocab_id):
        super().__init__()
        self.vocab_id=vocab_id

    async def on_submit(self,interaction:discord.Interaction):
        v=DB.db.execute("SELECT * FROM vocab WHERE id=? AND user_id=?",(self.vocab_id,uid(interaction))).fetchone()
        if not v:return await interaction.response.send_message("找不到你的單字卡。",ephemeral=True)
        # Deterministic exact matching; synonym/alternate-form checks require GPT review.
        normalize=lambda x:' '.join(x.strip().casefold().split())
        correct=normalize(str(self.answer))==normalize(v['term'])
        try:result=DB.vocab_grade(uid(interaction),self.vocab_id,correct,response=str(self.answer))
        except ValueError as ex:return await interaction.response.send_message(str(ex),ephemeral=True)
        embed=discord.Embed(title="✅ 回想成功" if correct else "🔁 需要複習",
            description=f"**你的答案：** {str(self.answer)}\n**收藏原詞：** {v['term']}\n"
                        f"**下次複習：** {result['due_at'][:16]}（台灣時間）\n\n"
                        "目前以收藏原詞精確比對；其他正確的變形或同義說法，仍須由 GPT 批改確認。",
            color=discord.Color.green() if correct else discord.Color.orange())
        await interaction.response.send_message(embed=embed,view=VocabNextView(interaction.user.id),ephemeral=True)


class VocabCardView(OwnedView):
    def __init__(self,owner_id,vocab):
        super().__init__(owner_id)
        self.vocab_id=vocab['id']
        self.revealed=False
        if not (vocab['note'] or '').strip():
            self.type_answer.disabled=True

    @discord.ui.button(label="⌨️ 輸入德文答案",style=discord.ButtonStyle.primary)
    async def type_answer(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.send_modal(VocabAnswerModal(self.vocab_id))

    @discord.ui.button(label="👁️ 顯示單字答案",style=discord.ButtonStyle.success)
    async def reveal(self,interaction:discord.Interaction,button:discord.ui.Button):
        if self.revealed:return await interaction.response.send_message("已顯示過答案。",ephemeral=True)
        self.revealed=True
        v=DB.db.execute("SELECT * FROM vocab WHERE id=? AND user_id=?",(self.vocab_id,uid(interaction))).fetchone()
        if not v:return await interaction.response.send_message("這張單字卡不存在。",ephemeral=True)
        emb=discord.Embed(title="🌿 單字回想｜揭曉答案",
            description=f"**{v['term']}**\n\n**來源：** {v['source'] or '個人收藏'}\n"
                        f"**自己的筆記：** {v['note'] or '尚未填寫（可用中文意思或例句作為下次的回想提示）'}\n\n"
                        "請按照『能否不看提示、自己正確使用』來評估。",color=discord.Color.green())
        await interaction.response.edit_message(embed=emb,view=VocabGradeView(interaction.user.id,self.vocab_id))

    @discord.ui.button(label="🏠 返回首頁",style=discord.ButtonStyle.secondary)
    async def back(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id))


class VocabGradeView(OwnedView):
    def __init__(self,owner_id,vocab_id):
        super().__init__(owner_id)
        self.vocab_id=vocab_id
        self.done=False

    async def grade(self,interaction,passed):
        if self.done:return await interaction.response.send_message("這張卡已記錄。",ephemeral=True)
        try: result=DB.vocab_grade(uid(interaction),self.vocab_id,passed)
        except ValueError as ex:return await interaction.response.send_message(str(ex),ephemeral=True)
        self.done=True
        emb=discord.Embed(title="🌿 單字回想已記錄",
            description=f"**{result['term']}**\n{'✅ 已能主動使用' if passed else '🔁 仍需要複習'}\n"
                        f"下次複習：{result['due_at'][:16]}（台灣時間）\n\n這是自我評估，並非 AI 文法批改。",
            color=discord.Color.green() if passed else discord.Color.orange())
        await interaction.response.edit_message(embed=emb,view=VocabNextView(interaction.user.id))

    @discord.ui.button(label="✅ 我能主動使用",style=discord.ButtonStyle.success)
    async def yes(self,interaction:discord.Interaction,button:discord.ui.Button):
        await self.grade(interaction,True)

    @discord.ui.button(label="🔁 我還不熟",style=discord.ButtonStyle.secondary)
    async def no(self,interaction:discord.Interaction,button:discord.ui.Button):
        await self.grade(interaction,False)


class VocabNextView(OwnedView):
    @discord.ui.button(label="🌿 下一張單字卡",style=discord.ButtonStyle.success)
    async def another(self,interaction:discord.Interaction,button:discord.ui.Button):
        await show_vocab_review(interaction,edit=True)

    @discord.ui.button(label="🏠 返回冒險首頁",style=discord.ButtonStyle.primary)
    async def home(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id))


async def show_vocab_review(interaction,edit=False):
    vocab=DB.vocab_pick(uid(interaction))
    if vocab:
        hint=(vocab['note'][:200] if vocab['note'] else '沒有中文提示；這張卡先用「顯示答案＋自評」。新增含中文筆記的詞才會開啟「輸入德文答案」。')
        embed=discord.Embed(title="🌿 詞語之樹｜主動單字回想",
            description=f"**來源：** {vocab['source'] or '個人收藏'}\n"
                        f"**自己的提示／筆記：** {hint}\n\n"
                        "先回想完整詞形（包括 Artikel），可以輸入答案自動比對，或顯示答案自行評估。",color=discord.Color.green())
        view=VocabCardView(interaction.user.id,vocab)
    else:
        embed=discord.Embed(title="🌿 詞語之樹",description="沒有可複習的單字卡。先收藏一些德文詞語，或等到下次複習時間。",color=discord.Color.green())
        view=BackView(interaction.user.id)
    if edit:await interaction.response.edit_message(embed=embed,view=view,attachments=[])
    else:await interaction.response.send_message(embed=embed,view=view,ephemeral=True)


async def start_media(interaction,skill,edit=False):
    q=DB.get_question(uid(interaction),skill=skill)
    if not q:
        msg=f"📚 {skill} 目前沒有新題或到期複習題，稍後再來挑戰。"
        if edit:await interaction.response.edit_message(content=msg,embed=None,view=BackView(interaction.user.id),attachments=[])
        else:await interaction.response.send_message(msg,ephemeral=True)
        return
    await send_quiz(interaction,q,edit=edit)


class BackView(OwnedView):
    @discord.ui.button(label="⬅️ 返回冒險首頁",style=discord.ButtonStyle.primary)
    async def back(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id),attachments=[])


def quest_board_embed(user_id):
    p=DB.profile(user_id)
    items=DB.quests(user_id)
    e=discord.Embed(title="🏰 公會佈告欄｜Abenteuerbuch",description=f"**主線第 {p['chapter']} 章**｜在奇幻德語世界中展開冒險。\n選擇下方任務查看 NPC、場景與進度。",color=discord.Color.gold())
    for q in items[:12]:
        st=DB.quest_state(user_id,q["id"])
        status={"locked":"🔒 未解鎖","active":"🧭 進行中","available":"✨ 可開始"}.get(q["status"],q["status"])
        e.add_field(name=f"{'📜' if q['kind']=='main' else '🌠'} {q['title']}｜{status}",
                    value=f"{q['description']}\n`{q['id']}`"[:950],inline=False)
    e.set_footer(text="已完成的章節會保留在資料庫；新章節需完成主線才解鎖。")
    return e


def quest_detail_embed(user_id,quest_id):
    st=DB.quest_state(user_id,quest_id)
    q,scene,phase=st["quest"],st["scene"],st["phase"]
    e=discord.Embed(title=("📜 主線｜" if q["kind"]=="main" else "🌠 支線｜")+q["title"],
                    description=f"**📍 {scene['location']}**\n\n{scene['opening']}\n\n**{scene['npc']}：**\n*„{scene['greeting']}“*",
                    color=discord.Color.purple())
    status={"locked":"🔒 尚未解鎖","available":"✨ 等待接受","active":"🧭 正在進行","completed":"🏆 已完成"}.get(q["status"],q["status"])
    e.add_field(name="🎯 任務目標",value=scene["goal"],inline=False)
    count=st["quiz_count"];goal=scene["minimum_quizzes"]
    steps=("① 探索場景 " + ("✅" if phase>=1 else "⬜") + "\n"
           + f"② 文法試煉 {min(count,goal)}/{goal} " + ("✅" if phase>=2 else "⬜") + "\n"
           + "③ 德文回覆 NPC " + ("✅ 已提交，待 GPT 批改" if phase>=3 else "⬜") + "\n"
           + "④ 領取獎勵 " + ("✅" if q["status"]=="completed" else "⬜"))
    e.add_field(name="🗺️ 任務進度",value=steps,inline=False)
    e.add_field(name="獎勵",value=f"✨ {q['xp']} XP｜🪙 {q['gold']} Gold",inline=False)
    if q["status"]=="locked":e.set_footer(text="先完成前置主線，或累積所需的練習次數。")
    else:e.set_footer(text="開放題的德文內容先記錄，週日再交由 ChatGPT 分析；任務獎勵代表參與完成。")
    return e


class QuestBoardView(OwnedView):
    def __init__(self,owner_id):
        super().__init__(owner_id)
        quests=DB.quests(str(owner_id))[:20]
        if quests:
            options=[discord.SelectOption(label=("主線 " if q["kind"]=="main" else "支線 ")+q["title"][:74],
                                          description={"locked":"尚未解鎖","active":"進行中","available":"可開始"}.get(q["status"],""),
                                          value=q["id"]) for q in quests]
            select=discord.ui.Select(placeholder="選擇想看的任務",options=options)
            async def on_select(interaction:discord.Interaction):
                qid=select.values[0]
                await interaction.response.edit_message(embed=quest_detail_embed(uid(interaction),qid),view=QuestDetailView(interaction.user.id,qid))
            select.callback=on_select
            self.add_item(select)

    @discord.ui.button(label="🏠 返回冒險首頁",style=discord.ButtonStyle.primary,row=1)
    async def home(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id))


class NPCReplyModal(discord.ui.Modal,title="💬 回覆公會 NPC"):
    antwort=discord.ui.TextInput(label="請用德文回答",style=discord.TextStyle.paragraph,
        placeholder="Ich heiße ... / Könntest du mir bitte helfen?",max_length=1200,required=True)

    def __init__(self,quest_id):
        super().__init__()
        self.quest_id=quest_id

    async def on_submit(self,interaction:discord.Interaction):
        try:rid=DB.submit_npc_answer(uid(interaction),self.quest_id,str(self.antwort))
        except ValueError as ex:return await say(interaction,str(ex))
        await interaction.response.send_message(
            f"✅ 已送出你的德文回答 `{rid}`。將於每週 ChatGPT 批改時分析文法。\n任務已達成，可領取 RPG 獎勵。",
            embed=quest_detail_embed(uid(interaction),self.quest_id),
            view=QuestDetailView(interaction.user.id,self.quest_id),ephemeral=True)


class QuestDetailView(OwnedView):
    def __init__(self,owner_id,quest_id):
        super().__init__(owner_id)
        self.quest_id=quest_id
        st=DB.quest_state(str(owner_id),quest_id)
        phase=st["phase"]
        if st["quest"]["status"]=="locked":
            action_label="🔒 任務尚未解鎖"
        elif phase==0:action_label="🗺️ 進入場景、接受任務"
        elif phase==1:action_label="⚔️ 開始文法試煉"
        elif phase==2:action_label="💬 用德文回覆 NPC"
        else:action_label="🎁 領取任務獎勵"
        action=discord.ui.Button(label=action_label[:80],style=discord.ButtonStyle.success,row=0,
                                 disabled=st["quest"]["status"]=="locked")
        action.callback=self.take_action
        self.add_item(action)

    async def take_action(self,interaction:discord.Interaction):
        st=DB.quest_state(uid(interaction),self.quest_id)
        phase=st["phase"]
        try:
            if phase==0:
                DB.start_quest(uid(interaction),self.quest_id)
                await interaction.response.edit_message(embed=quest_detail_embed(uid(interaction),self.quest_id),view=QuestDetailView(interaction.user.id,self.quest_id))
            elif phase==1:
                q=DB.get_question(uid(interaction),skill=st["quest"]["skill"])
                if not q:q=DB.get_question(uid(interaction))
                if not q:
                    return await interaction.response.send_message("目前新題與到期複習題都用完了，需等下一批題目或到期後繼續試煉。",ephemeral=True)
                await send_quiz(interaction,q,self.quest_id,edit=True)
            elif phase==2:
                await interaction.response.send_modal(NPCReplyModal(self.quest_id))
            else:
                result=DB.finish_quest(uid(interaction),self.quest_id)
                await interaction.response.edit_message(
                    embed=discord.Embed(title="🏆 任務完成！",description=f"完成 **{result['title']}**！\n✨ +{result['xp']} XP｜🪙 +{result['gold']} Gold\n新的主線或支線可能已解鎖。",color=discord.Color.gold()),
                    view=QuestBoardView(interaction.user.id))
        except ValueError as ex:
            await interaction.response.send_message(str(ex),ephemeral=True)

    @discord.ui.button(label="🏰 返回公會任務",style=discord.ButtonStyle.secondary,row=1)
    async def board(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=quest_board_embed(uid(interaction)),view=QuestBoardView(interaction.user.id))

    @discord.ui.button(label="🏠 返回冒險首頁",style=discord.ButtonStyle.primary,row=1)
    async def home(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.response.edit_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id))


@de.command(name="help",description="操作手冊與 ChatGPT Plus 批改流程")
async def help_cmd(interaction:discord.Interaction):
    listening_help="｜`/de hoeren` Windows 本機德語聽力" if LISTENING_ENABLED else "（雲端版暫停聽力）"
    await say(interaction,"**📚 Die Sprachchroniken V1.7**\n`/de daily` 冒險首頁｜`/de practice` 文法題（優先新題＋錯題複習）｜`/de quizstats` 查看題庫狀態｜`/de quizhistory` 答題對錯紀錄\n`/de diary` 日記｜`/de vocab add` 單字｜`/de vocab review` 單字回想｜`/de skills` 技能｜`/de quest` 公會任務\n`/de lesen` 閱讀"+listening_help+"｜`/de journal` 今日足跡｜`/de progress` 開拓進度｜`/de streak` 學習熱力圖\n`/de review reminder` 開／關週日 20:00 私訊提醒｜`/de review status` 待批改狀態｜`/de review resend` 重送舊批次\n`/de review export` 匯出給 ChatGPT → `/de review import` 上傳回傳檔 → `/de review confirm` 確認寫入。\n`/de sync export` 下載完整進度 → `/de sync import` 上傳另一端進度 → `/de sync confirm` 確認覆蓋。\n"+("`/de shutdown` 僅管理員可用，正常結束本次雲端運作。\n" if OWNER_ID else "")+"**注意**：自由寫作不會立即判分；主線 NPC 回答會記錄，週末再交 GPT 分析。")


@de.command(name="diary",description="寫一段德文日記，等待每週批改")
@app_commands.describe(text="你的德文句子")
async def diary(interaction:discord.Interaction,text:str):
    try:rid=DB.add_record(uid(interaction),"diary",text)
    except ValueError as e:return await say(interaction,str(e))
    await say(interaction,f"📖 已收藏日記 `{rid}`。每週匯出交給 ChatGPT 分析。")


@de.command(name="collect",description="收藏從 Netflix、書籍或生活看到的德文")
@app_commands.describe(text="德文句子",source="來源（例如 Netflix）")
async def collect(interaction:discord.Interaction,text:str,source:str="personal"):
    try:rid=DB.add_record(uid(interaction),"collection",text,source=source)
    except ValueError as e:return await say(interaction,str(e))
    await say(interaction,f"✨ 已收藏句子 `{rid}`，來源：{source[:60]}。")


@vocab_group.command(name="add",description="加入單字，週末補全字族、搭配詞與文化故事")
async def vocab_add(interaction:discord.Interaction,term:str,source:str="personal",note:str=""):
    try:vid=DB.add_vocab(uid(interaction),term,source,note)
    except ValueError as e:return await say(interaction,str(e))
    await say(interaction,f"🌿 {'已收藏：'+term if vid else '這個詞已經收藏過了：'+term}。")


@de.command(name="practice",description="取得一題德文練習")
@app_commands.describe(skill="留空表示隨機技能；例如 Kasus、Verben、Satzbau")
async def practice(interaction:discord.Interaction,skill:str=""):
    if skill and skill not in SKILLS:return await say(interaction,"未知技能；使用 `/de skills` 查看分類。")
    q=DB.get_question(uid(interaction),skill or None)
    if not q:
        ov=DB.quiz_overview(uid(interaction),skill or None)
        return await say(interaction,f"🎉 沒有新題或到期複習題了。新題 {ov['new']}｜到期 {ov['due']}｜等待複習 {ov['waiting']}。可等題目到期或每週匯入新題庫。")
    await send_quiz(interaction,q)


@de.command(name="answer",description="用選項編號回答題目")
async def answer(interaction:discord.Interaction,question_id:str,choice:int):
    q=DB.db.execute("SELECT * FROM questions WHERE id=? AND (owner_id IS NULL OR owner_id=?)",(question_id,uid(interaction))).fetchone()
    if not q:return await say(interaction,"找不到題目。")
    opts=json.loads(q["options"])
    if choice<1 or choice>len(opts):return await say(interaction,f"請輸入 1–{len(opts)}。")
    try:correct,expected,explanation,selected=DB.answer_choice(uid(interaction),question_id,choice-1)
    except ValueError as e:return await say(interaction,str(e))
    await say(interaction,f"{'✅ 答對了！+10 XP' if correct else '❌ 答錯了！+0 XP'}\n你的選擇：**{selected}**\n正確答案：**{expected}**\n{explanation}")


@de.command(name="quick",description="零碎時間快速練習")
async def quick(interaction:discord.Interaction,minutes:app_commands.Range[int,1,15]=3):
    q=DB.get_question(uid(interaction))
    if not q:return await say(interaction,"🎉 新題和到期複習已全部完成。過一陣子再回來，或透過 ChatGPT 週批改匯入新題。")
    embed=quiz_embed(q)
    embed.set_footer(text=f"{minutes} 分鐘碎片練習｜答完可再次使用 /de quick（尚無自動計時）")
    await send_quiz(interaction,q)


@de.command(name="quizstats",description="查看新題、錯題及下次複習進度")
async def quizstats(interaction:discord.Interaction):
    ov=DB.quiz_overview(uid(interaction))
    review=DB.db.execute("""SELECT q.skill,COUNT(*) n FROM quiz_progress p JOIN questions q ON q.id=p.question_id
        WHERE p.user_id=? AND p.wrong_count>0 AND p.streak=0 GROUP BY q.skill ORDER BY n DESC""",(uid(interaction),)).fetchall()
    topics=", ".join(f"{r['skill']} {r['n']}題" for r in review) or "目前沒有待修正的錯題"
    await say(interaction,f"📚 **題庫進度**\n✨ 未見過的新題：{ov['new']}\n🧠 到期複習：{ov['due']}\n⏳ 尚未到期：{ov['waiting']}\n🔎 目前待加強：{topics}\n下一次複習：{ov['next_due'] or '暫無'}")


@de.command(name="quizhistory",description="最近的文法題答題歷史與對錯記錄")
async def quizhistory(interaction:discord.Interaction):
    rows=DB.quiz_history(uid(interaction))
    if not rows:return await say(interaction,"還沒有作答紀錄。先使用 `/de practice` 開始第一題吧。")
    lines=[f"{'✅' if row['correct'] else '❌'} `{row['question_id']}` [{row['skill']}] {row['prompt'][:75]}\n你的答案：{row['response']}" for row in rows]
    await say(interaction,"📜 **最近 12 題的作答紀錄**\n"+"\n".join(lines))


@de.command(name="daily",description="今日推薦任務")
async def daily(interaction:discord.Interaction):
    await interaction.response.send_message(embed=home_embed(uid(interaction)),view=HomeView(interaction.user.id),ephemeral=True)


@de.command(name="journal",description="查看今天的冒險日誌與每項學習紀錄")
async def journal(interaction:discord.Interaction,day:str=""):
    from datetime import date
    if day:
        try:
            selected=date.fromisoformat(day)
        except ValueError:return await say(interaction,"日期格式請使用 YYYY-MM-DD，例如 2026-11-04")
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if selected>datetime.now(ZoneInfo('Asia/Taipei')).date():return await say(interaction,"不能查詢未來日期。")
    await interaction.response.send_message(embed=journal_embed(uid(interaction),day or None),
        view=JournalView(interaction.user.id,day or None),ephemeral=True)


@de.command(name="progress",description="查看 XP、主線、文化與文法題的文字進度條")
async def progress(interaction:discord.Interaction):
    await interaction.response.send_message(embed=overview_embed(uid(interaction)),view=BackView(interaction.user.id),ephemeral=True)


@de.command(name="streak",description="查看過去 365 天的學習熱力圖、目前與最佳連續天數")
async def streak(interaction:discord.Interaction):
    await show_streak(interaction)


@de.command(name="lesen",description="閱讀短篇德文情境並回答理解題")
async def lesen(interaction:discord.Interaction):
    await start_media(interaction,"Lesen")


@de.command(name="hoeren",description="本機德語語音聽力選擇題（Windows SAPI 離線）")
async def hoeren(interaction:discord.Interaction):
    if not LISTENING_ENABLED:
        return await say(interaction,"🎧 雲端文字模式已暫停聽力；回到 Windows 本機版即可使用德語語音。")
    await start_media(interaction,"Hoeren")


_shutdown_started=False
_auto_shutdown_task=None


async def stop_bot():
    """A clean exit is not restarted by Railway's On Failure policy."""
    global _shutdown_started
    if _shutdown_started:
        return
    _shutdown_started=True
    print("Session finished; closing Discord connection.")
    await bot.close()


async def auto_shutdown():
    await asyncio.sleep(AUTO_SHUTDOWN_SECONDS)
    print("Session time limit reached; stopping bot.")
    await stop_bot()


@de.command(name="shutdown",description="管理員專用：正常關閉本次雲端使用")
async def shutdown_cmd(interaction:discord.Interaction):
    if not OWNER_ID or uid(interaction)!=OWNER_ID:
        return await say(interaction,"⛔ 只有 BOT_OWNER_ID 指定的管理員能關閉 Bot。")
    await say(interaction,"🛑 已收到關機指令。Bot 即將離線；SQLite 進度會保留在設定的資料庫中。")
    await asyncio.sleep(0.25)
    await stop_bot()


async def sync_owner_check(interaction:discord.Interaction) -> bool:
    if OWNER_ID and uid(interaction)==OWNER_ID:
        return True
    await say(interaction,"⛔ 同步涉及所有學習紀錄，只允許 BOT_OWNER_ID 指定的管理員操作。")
    return False


def sync_overview_line(summary):
    return (f"✨ XP {summary.xp}｜📝 日記／句子 {summary.records}｜🌿 單字 {summary.vocab}"
            f"｜⚔️ 作答 {summary.attempts}｜📜 活動 {summary.activities}｜👥 使用者 {summary.users}")


@sync_group.command(name="status",description="查看目前裝置的同步版本與是否有未匯出的新進度")
async def sync_status(interaction:discord.Interaction):
    if not await sync_owner_check(interaction):return
    stamp=SYNC.checkpoint()
    changed=bool(stamp and SYNC.current_hash()!=stamp.content_hash)
    await say(interaction,
        "📦 **Sprachchroniken 同步狀態**\n"
        +f"裝置：{SYNC.origin}\n"
        +(f"最近快照：`{stamp.snapshot_id[:12]}`｜{stamp.created_at} UTC｜來源 {stamp.origin}\n"
          if stamp else "最近快照：尚未匯出／匯入\n")
        +f"本機新增修改：{'⚠️ 有，請先匯出' if changed else '沒有偵測到' if stamp else '尚無基準版本'}\n"
        +sync_overview_line(SYNC.summary()))


@sync_group.command(name="export",description="下載完整 SQLite 進度備份（僅管理員可見）")
async def sync_export(interaction:discord.Interaction):
    if not await sync_owner_check(interaction):return
    await interaction.response.defer(ephemeral=True,thinking=True)
    path=None
    try:
        path,stamp=SYNC.export()
        safe_label="".join(c if c.isalnum() and c.isascii() else "_" for c in stamp.origin)[:24]
        filename=f"sprachchroniken_{safe_label}_{stamp.snapshot_id[:10]}.sqlite3"
        uploaded=discord.File(str(path),filename=filename)
        try:
            await interaction.followup.send(
                "📦 **完整進度已匯出**（僅你可見）\n"
                +f"來源：{stamp.origin}｜版本 `{stamp.snapshot_id[:12]}`\n"
                +sync_overview_line(SYNC.summary())
                +"\n請先下載此檔案，關閉目前 Bot，再到另一端使用 `/de sync import`。",
                file=uploaded,ephemeral=True)
        finally:
            uploaded.close()
    except (SyncError,sqlite3.Error,OSError,discord.HTTPException) as ex:
        await interaction.followup.send(f"❌ 匯出失敗：{str(ex)[:250]}",ephemeral=True)
    finally:
        if path:path.unlink(missing_ok=True)


@sync_group.command(name="import",description="上傳另一端的 SQLite 進度備份，先預覽而不覆蓋")
@app_commands.describe(file="透過 /de sync export 下載的 .sqlite3 備份")
async def sync_import(interaction:discord.Interaction,file:discord.Attachment):
    if not await sync_owner_check(interaction):return
    if file.size<=0 or file.size>MAX_BACKUP_BYTES:
        return await say(interaction,"❌ 只接受 15 MB 以內的 Sprachchroniken SQLite 備份。")
    await interaction.response.defer(ephemeral=True,thinking=True)
    path=None
    try:
        payload=await file.read()
        if len(payload)!=file.size or len(payload)>MAX_BACKUP_BYTES:
            raise SyncError("附件大小不一致或超過 15 MB。")
        fd,name=tempfile.mkstemp(prefix="sprachchroniken_import_",suffix=".sqlite3")
        path=Path(name)
        with os.fdopen(fd,"wb") as stream:
            stream.write(payload)
        preview=SYNC.preview(path)
        old=PENDING_SYNC_IMPORTS.pop(uid(interaction),None)
        if old:old["path"].unlink(missing_ok=True)
        PENDING_SYNC_IMPORTS[uid(interaction)]={
            "path":path,"preview":preview,"created":time.monotonic()
        }
        path=None  # Ownership transferred to the pending import.
        issues="\n".join(f"• {warning}" for warning in preview.warnings) or "✅ 來源接續目前版本，未發現進度衝突。"
        await interaction.followup.send(
            "📥 **匯入預覽：尚未覆蓋**\n"
            +f"來源：{preview.checkpoint.origin}｜{preview.checkpoint.created_at} UTC\n"
            +"**匯入資料：** "+sync_overview_line(preview.overview)+"\n"
            +"**目前資料：** "+sync_overview_line(preview.target_overview)+"\n"
            +issues+"\n\n⚠️ 這是整份資料庫取代，不會合併兩邊進度。"
            +"\n15 分鐘內輸入 `/de sync confirm confirmation:REPLACE` 才會正式覆蓋。",
            ephemeral=True)
    except (SyncError,sqlite3.Error,OSError,discord.HTTPException) as ex:
        await interaction.followup.send(f"❌ 匯入預覽失敗：{str(ex)[:250]}",ephemeral=True)
    finally:
        if path:path.unlink(missing_ok=True)


@sync_group.command(name="confirm",description="輸入 REPLACE 確認完整覆蓋目前進度（先自動備份）")
@app_commands.describe(confirmation="請輸入 REPLACE，確認取代目前裝置所有進度")
async def sync_confirm(interaction:discord.Interaction,confirmation:str):
    if not await sync_owner_check(interaction):return
    if confirmation!="REPLACE":
        return await say(interaction,"⛔ 必須輸入大寫 `REPLACE` 才會覆蓋；目前資料沒有變動。")
    pending=PENDING_SYNC_IMPORTS.get(uid(interaction))
    if not pending:
        return await say(interaction,"沒有待確認的同步檔案。請先用 `/de sync import` 上傳並預覽。")
    if time.monotonic()-pending["created"]>15*60:
        PENDING_SYNC_IMPORTS.pop(uid(interaction),None)
        pending["path"].unlink(missing_ok=True)
        return await say(interaction,"同步預覽已超過 15 分鐘，請重新上傳以確認最新資料。")
    await interaction.response.defer(ephemeral=True,thinking=True)
    try:
        saved=SYNC.restore(pending["path"],pending["preview"].target_hash)
        PENDING_IMPORTS.clear()  # Drop old weekly review previews after DB replacement.
        await interaction.followup.send(
            "✅ **完整學習進度已取代成功！**\n"
            +sync_overview_line(SYNC.summary())
            +f"\n舊資料已自動備份至此裝置的 `{saved.name}`。"
            +"\n現在可以使用 `/de profile`、`/de journal` 驗證進度。",ephemeral=True)
    except (SyncError,sqlite3.Error,OSError) as ex:
        await interaction.followup.send(f"❌ 確認匯入失敗：{str(ex)[:300]}",ephemeral=True)
    finally:
        PENDING_SYNC_IMPORTS.pop(uid(interaction),None)
        pending["path"].unlink(missing_ok=True)


@vocab_group.command(name="review",description="複習自己收藏的詞彙或片語")
async def vocab_review(interaction:discord.Interaction):
    await show_vocab_review(interaction)


@de.command(name="profile",description="角色資料")
async def profile(interaction:discord.Interaction):
    p=DB.profile(uid(interaction))
    await say(interaction,f"🛡️ **{interaction.user.display_name}**\n{p['rank']}｜Lv.{p['level']}｜Chapter {p['chapter']}\n✨ XP: {p['xp']}｜🪙 Gold: {p['gold']}\n📝 待批改：{p['pending']}\n📚 文化領土 `/de culture map`｜技能 `/de skills`。")


@de.command(name="skills",description="查看德文技能統計與分類")
async def skills(interaction:discord.Interaction):
    p=DB.profile(uid(interaction));counts={r['skill']:(r['correct'],r['total']) for r in p['skills']}
    result=[f"• {skill}: {counts[skill][0]}/{counts[skill][1]} 正確" if skill in counts else f"• {skill}: 尚未評估" for skill in sorted(SKILLS)]
    await say(interaction,"📚 **德文技能樹（客觀題紀錄，不等於 CEFR）**\n"+"\n".join(result))


@de.command(name="quest",description="進入公會冒險佈告欄與 NPC 劇情")
async def quest(interaction:discord.Interaction):
    await interaction.response.send_message(embed=quest_board_embed(uid(interaction)),view=QuestBoardView(interaction.user.id),ephemeral=True)


@de.command(name="finish",description="領取已完成劇情試煉的任務獎勵（舊指令）")
async def finish(interaction:discord.Interaction,quest_id:str):
    try:q=DB.finish_quest(uid(interaction),quest_id)
    except ValueError as e:return await say(interaction,str(e))
    await say(interaction,f"🏆 完成 **{q['title']}**！+{q['xp']} XP、+{q['gold']} Gold。")


@culture_group.command(name="map",description="五大文化領土完成率")
async def culture_map(interaction:discord.Interaction):
    rows=DB.culture(uid(interaction));groups={c:[r for r in rows if r['category']==c] for c in CULTURES}
    parts=[]
    for c,items in sorted(groups.items()):
        found=sum(r['state']>=1 for r in items);mastered=sum(r['state']==3 for r in items)
        parts.append(f"**{c}** `{progress_bar(found,len(items))}` 探索 {found}/{len(items)} ({100*found//max(1,len(items))}%)｜掌握 {mastered}/{len(items)}")
    await say(interaction,"🗺️ **Die Karte der Kulturen**\n"+"\n".join(parts)+"\n使用 `/de culture list` 查看知識節點。")


@culture_group.command(name="list",description="查看文化領土中的知識點")
async def culture_list(interaction:discord.Interaction,category:str=""):
    if category and category not in CULTURES:return await say(interaction,"分類："+", ".join(sorted(CULTURES)))
    rows=DB.culture(uid(interaction),category or None)
    await say(interaction,"📜 **文化節點**\n"+"\n".join(f"{'⭐' if r['state']==3 else '📖' if r['state']==2 else '👁️' if r['state']==1 else '▫️'} `{r['id']}` {r['title']} ({r['country']})" for r in rows))


@culture_group.command(name="discover",description="標記已接觸的文化知識（不等於掌握）")
async def culture_discover(interaction:discord.Interaction,node_id:str):
    try:DB.culture_discover(uid(interaction),node_id)
    except ValueError as e:return await say(interaction,str(e))
    await say(interaction,f"👁️ 已發現 `{node_id}`。理解與掌握狀態將透過每週驗證後更新。")


@review_group.command(name="reminder",description="設定每週日 20:00（台灣時間）的 GPT 日記批改私訊提醒")
@app_commands.describe(enabled="True 開啟提醒，False 停用提醒")
async def review_reminder(interaction:discord.Interaction,enabled:bool=True):
    DB.set_reminder(uid(interaction),enabled)
    await say(interaction,"🔔 已開啟每週日 20:00 的日記批改提醒。若 Bot 當時離線，下次上線會補提醒（需仍有待批改日記）。" if enabled else "🔕 已關閉每週日記批改私訊提醒。仍可手動使用 /de review export。")


@review_group.command(name="due",description="到期的個人化複習")
async def due(interaction:discord.Interaction):
    rows=DB.pending_reviews(uid(interaction))
    await say(interaction,"🧠 **待複習項目**\n"+("\n".join(f"`{r['id']}` {r['corrected'] or '(查看原始紀錄)'}" for r in rows) if rows else "目前沒有到期的個人化複習。"))


@review_group.command(name="status",description="查看每週批改紀錄狀態")
async def review_status(interaction:discord.Interaction):
    DB.user(uid(interaction))
    rows=DB.db.execute("SELECT status,COUNT(*) n FROM records WHERE user_id=? GROUP BY status",(uid(interaction),)).fetchall()
    d={r['status']:r['n'] for r in rows}
    await say(interaction,f"📦 **批改狀態**\n未匯出：{d.get('pending',0)}｜已匯出待批改：{d.get('exported',0)}｜已批改：{d.get('reviewed',0)}")


@review_group.command(name="export",description="匯出尚未批改的學習紀錄 JSON")
async def review_export(interaction:discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data=DB.export(uid(interaction))
    content=json.dumps(data,ensure_ascii=False,indent=2).encode("utf-8")
    file=discord.File(io.BytesIO(content),filename=f"de_review_{data['batch_id']}.json")
    await interaction.followup.send(f"📤 批次 `{data['batch_id']}`｜{len(data['records'])} 筆待批改紀錄。上傳至 ChatGPT 並附上 `CHATGPT_PROMPT.md` 的指示，再將回傳檔匯入。",file=file,ephemeral=True)


@review_group.command(name="resend",description="重新下載之前匯出、仍待 ChatGPT 批改的 JSON")
async def review_resend(interaction:discord.Interaction,batch_id:str=""):
    try: data=DB.resend_export(uid(interaction),batch_id or None)
    except ValueError as e:return await say(interaction,str(e))
    content=json.dumps(data,ensure_ascii=False,indent=2).encode("utf-8")
    await interaction.response.send_message(
        f"📎 重新下載批次 `{data['batch_id']}`（不會重新建立或重複匯出）。",
        file=discord.File(io.BytesIO(content),filename=f"de_review_{data['batch_id']}.json"),ephemeral=True)


PENDING_IMPORTS={}


@review_group.command(name="import",description="上傳 ChatGPT 回傳的 JSON，先預覽不寫入")
async def review_import(interaction:discord.Interaction,file:discord.Attachment):
    if not file.filename.lower().endswith(".json") or file.size>2_000_000:return await say(interaction,"只接受最大 2 MB 的 .json 檔。")
    await interaction.response.defer(ephemeral=True)
    try:
        payload=json.loads((await file.read()).decode("utf-8"))
        summary=DB.import_preview(uid(interaction),payload)
    except (UnicodeError,json.JSONDecodeError,ValueError,TypeError,KeyError) as e:
        return await interaction.followup.send(f"❌ 驗證未通過：{str(e)[:300]}",ephemeral=True)
    PENDING_IMPORTS[uid(interaction)]=payload
    await interaction.followup.send(f"✅ 驗證通過：`{summary['batch_id']}`\n批改 {summary['corrections']}｜新題目 {summary['questions']}｜新任務 {summary['quests']}｜文化更新 {summary['culture_updates']}｜仍待批改 {summary['unreviewed']}\n**尚未寫入資料庫**。請執行 `/de review confirm`。",ephemeral=True)


@review_group.command(name="confirm",description="確認寫入剛剛預覽的 AI 批改")
async def review_confirm(interaction:discord.Interaction):
    payload=PENDING_IMPORTS.get(uid(interaction))
    if not payload:return await say(interaction,"目前沒有待確認的匯入檔；請先使用 `/de review import`。")
    try:summary=DB.import_apply(uid(interaction),payload)
    except (ValueError,sqlite3.Error,KeyError,TypeError) as e:return await say(interaction,f"❌ 匯入失敗：{str(e)[:250]}")
    PENDING_IMPORTS.pop(uid(interaction),None)
    await say(interaction,f"✅ `{summary['batch_id']}` 匯入成功！下週題目、文化知識與任務已更新。")


@tasks.loop(minutes=5)
async def weekly_diary_reminders():
    """Once per Sunday cutoff. Catches up after restart; never relies on an in-process timer."""
    for user_id,count,cutoff in DB.due_reminder_users():
        try:
            user=bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
            await user.send(
                f"📣 **Die Sprachchroniken｜週日 GPT 批改提醒**\n"
                f"截至 {cutoff}（台灣時間週日 20:00），你有 **{count} 筆**日記／NPC 德文回答尚待批改。\n"
                "使用 `/de review status` 查看狀態，然後 `/de review export` 匯出 JSON 給 ChatGPT Plus。\n"
                "如果你已匯出，請記得完成 ChatGPT 批改後的 `/de review import` 和 `confirm`。\n"
                "可用 `/de review reminder enabled:False` 關閉私訊提醒。")
            DB.mark_reminder(user_id,cutoff,"sent")
        except (discord.Forbidden,discord.HTTPException,ValueError) as ex:
            print(f"Reminder DM unavailable for user {user_id}: {type(ex).__name__}")
            DB.mark_reminder(user_id,cutoff,"failed")


@weekly_diary_reminders.before_loop
async def before_weekly_reminders():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    global _auto_shutdown_task
    print(f"Die Sprachchroniken connected: {bot.user}")
    if AUTO_SHUTDOWN_SECONDS and _auto_shutdown_task is None:
        _auto_shutdown_task=asyncio.create_task(auto_shutdown(),name="session-auto-shutdown")
        print(f"Session auto-shutdown in {AUTO_SHUTDOWN_SECONDS / 3600:g} hour(s).")


async def setup_commands():
    bot.tree.add_command(de)
    if not weekly_diary_reminders.is_running():
        weekly_diary_reminders.start()
    gid=os.getenv("DISCORD_GUILD_ID","").strip()
    if gid:
        guild=discord.Object(id=int(gid))
        bot.tree.copy_global_to(guild=guild)
        synced=await bot.tree.sync(guild=guild)
        print(f"✅ 已同步 {len(synced)} 個伺服器指令群組")
    else:
        synced=await bot.tree.sync()
        print(f"✅ 已同步 {len(synced)} 個全域指令群組")


bot.setup_hook=setup_commands


if __name__=="__main__":
    if not TOKEN or TOKEN=="put_your_discord_bot_token_here":
        raise RuntimeError("請在 .env 設定 DISCORD_TOKEN")
    try:
        bot.run(TOKEN)
    finally:
        DB.db.commit()
        DB.db.close()
