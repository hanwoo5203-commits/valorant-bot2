import asyncio
import datetime as dt_mod
from datetime import datetime
import io
import itertools
import json
import os
import random
import shutil
from threading import Thread
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask
import matplotlib.pyplot as plt
from pymongo import MongoClient
import pytz

# --- [1. Render 24시간 유지를 위한 Flask 웹서버 설정] ---
app = Flask("")


@app.route("/")
def home():
  return "Bot is alive!"


def run_web():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


def keep_alive():
  t = Thread(target=run_web)
  t.start()


keep_alive()

# --- [2. 디스코드 봇 기본 설정] ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- [3. MongoDB 클라우드 영구 저장소 설정] ---
MONGO_URI = os.environ.get("MONGO_URI")

if MONGO_URI:
  try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["discord_bot_db"]
    data_collection = db["bot_data"]
    print("🍃 MongoDB 클라우드에 성공적으로 연결되었습니다!")
  except Exception as e:
    print(f"❌ MongoDB 연결 실패: {e}")
    data_collection = None
else:
  data_collection = None


def load_data():
  if data_collection is not None:
    try:
      doc = data_collection.find_one({"_id": "main_data"})
      if doc:
        print("🍃 클라우드(MongoDB)에서 최신 데이터를 불러왔습니다!")
        doc.pop("_id", None)
        return doc
    except Exception as e:
      print(f"⚠️ MongoDB 로드 오류: {e}")

  # 로컬 파일 백업 불러오기 (안전장치)
  if os.path.exists("data.json") and os.path.getsize("data.json") > 0:
    try:
      with open("data.json", "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      pass

  return {
      "users": {},
      "shop": {},
      "user_stocks": {},
      "bot_admins": [1030754198796632135],
  }


def save_data(data):
  # 1. 로컬 파일 보조 저장
  try:
    temp_file = "data.json.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
      json.dump(data, f, ensure_ascii=False, indent=4)
      f.flush()
      os.fsync(f.fileno())
    os.replace(temp_file, "data.json")
  except Exception as e:
    print(f"로컬 저장 실패: {e}")

  # 2. MongoDB 클라우드 무제한 동기화
  if data_collection is not None:
    try:
      save_doc = data.copy()
      save_doc["_id"] = "main_data"
      data_collection.replace_one({"_id": "main_data"}, save_doc, upsert=True)
    except Exception as e:
      print(f"🍃 MongoDB 동기화 오류: {e}")


data = load_data()

if "bot_admins" not in data:
  data["bot_admins"] = []
  save_data(data)


def get_user_data(user_id):
  user_str = str(user_id)
  if user_str not in data["users"]:
    data["users"][user_str] = {
        "points": 0,
        "inventory": [],
        "last_checkin": "",
    }
    save_data(data)
  elif "last_checkin" not in data["users"][user_str]:
    data["users"][user_str]["last_checkin"] = ""
    save_data(data)
  return data["users"][user_str]


def get_user_points(user_id):
  return get_user_data(user_id)["points"]


def update_user_points(user_id, amount):
  user_str = str(user_id)
  get_user_data(user_id)
  data["users"][user_str]["points"] += amount
  save_data(data)
  return data["users"][user_str]["points"]


# -------------------------------------------------------------
# 👑 [최고 권한 체크] 오직 '나(개발자)' 단 한 사람만 승인하는 함수
# -------------------------------------------------------------
MY_DISCORD_ID = 1030754198796632135  # 본인의 디스코드 사용자 ID


def is_bot_admin_check(interaction: discord.Interaction) -> bool:
  # 서버 소유자나 일반 관리자 목록을 무시하고, 오직 본인 ID일 때만 True 반환!
  return interaction.user.id == MY_DISCORD_ID


# --- 전역 상태 데이터 ---
queue_5v5 = []
is_open_5v5 = False
reserved_time_5v5 = None
reserved_channel_5v5 = None

queue_1v1 = []
is_open_1v1 = False
last_bracket_embed = None

queue_fifa = []
fifa_winners = []
current_tournament_round = 0
last_fifa_group_embed = None
tournament_match_wins = {}
fifa_groups = {}
fifa_stats = {}

user_wins_1v1 = {}
banned_users = {}

stock_data = {
    "SK다우닉스": {
        "price": 300000,
        "status": "normal",
        "resume_time": 0,
        "history": [300000],
    },
    "야건식품": {
        "price": 3000,
        "status": "normal",
        "resume_time": 0,
        "history": [3000],
    },
    "야멧돼농협": {
        "price": 50000,
        "status": "normal",
        "resume_time": 0,
        "history": [50000],
    },
}

# 주식 시장 강제 차단 여부 및 1~2시간 랜덤 이벤트 타이머
stock_market_force_closed = False
next_stock_update_time = time.time() + random.randint(3600, 7200)


def get_tier_info(wins: int):
  if wins >= 150:
    return "🐐 G.O.A.T"
  elif wins >= 100:
    return "🔮 불멸"
  elif wins >= 50:
    return "💎 다이아몬드"
  elif wins >= 30:
    return "💎 플래티넘"
  elif wins >= 15:
    return "🥇 골드"
  elif wins >= 7:
    return "🥈 실버"
  elif wins >= 3:
    return "🥉 브론즈"
  else:
    return "⚙️ 아이언"


def get_or_init_fifa_stat(name: str):
  if name not in fifa_stats:
    fifa_stats[name] = {
        "win": 0,
        "draw": 0,
        "loss": 0,
        "gf": 0,
        "ga": 0,
        "gd": 0,
        "pts": 0,
    }
  return fifa_stats[name]


# ==========================================
# 백그라운드 루프
# ==========================================
@tasks.loop(seconds=30)
async def check_reservation_loop():
  global is_open_5v5, reserved_time_5v5, reserved_channel_5v5
  global next_stock_update_time, stock_data, stock_market_force_closed

  if reserved_time_5v5 is not None:
    now_kst = datetime.now(dt_mod.timezone(dt_mod.timedelta(hours=9)))
    current_time_str = now_kst.strftime("%H:%M")

    if current_time_str == reserved_time_5v5:
      is_open_5v5 = True
      target_channel = reserved_channel_5v5
      reserved_time_5v5 = None
      reserved_channel_5v5 = None

      if target_channel:
        await target_channel.send(
            "🚨 **[5v5 선착순 모집 시작]** 약속된 시간이 되었습니다! 지금부터 `/참가`"
            " 명령어를 입력하세요!"
        )

  # 주식 시장이 강제 차단되어 있으면 아래 주가 변동 및 이벤트 루프를 건너뜁니다.
  if stock_market_force_closed:
    return

  # 평소 미세 횡보 제어 (0시~7시는 완전 고정, 그 외는 -0.5%~+0.5% 횡보)
  kst = pytz.timezone("Asia/Seoul")
  now_kst = datetime.now(kst)
  current_hour = now_kst.hour

  if not (0 <= current_hour < 7):
    for stock_name, stock_info in stock_data.items():
      if stock_info.get("status") == "bankrupt":
        continue
      flat_change = random.uniform(-0.005, 0.005)
      old_price = stock_info["price"]
      new_price = max(100, int(old_price * (1 + flat_change)))
      stock_info["price"] = new_price

  # 1~2시간 랜덤 주기로 터지는 대폭등 & 부도 이벤트 체크
  if time.time() >= next_stock_update_time:
    await trigger_random_stock_event()
    next_stock_update_time = time.time() + random.randint(3600, 7200)


async def trigger_random_stock_event():
  global stock_data, stock_market_force_closed
  if stock_market_force_closed:
    return

  news_channel_id = os.environ.get("NEWS_CHANNEL_ID")
  news_channel = None
  if news_channel_id:
    news_channel = bot.get_channel(int(news_channel_id))
  else:
    for guild in bot.guilds:
      for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
          news_channel = channel
          break
      if news_channel:
        break

  kst = pytz.timezone("Asia/Seoul")
  current_hour = datetime.now(kst).hour

  if 0 <= current_hour < 7:
    return

  is_night_fluctuation = current_hour >= 21 or current_hour < 8

  for stock_name, stock_info in stock_data.items():
    if stock_info.get("status") == "bankrupt":
      if time.time() < stock_info.get("resume_time", 0):
        continue
      else:
        stock_info["status"] = "normal"

    if is_night_fluctuation:
      fluctuation = random.uniform(-0.02, 0.03)
      old_price = stock_info["price"]
      new_price = max(100, int(old_price * (1 + fluctuation)))
      stock_info["price"] = new_price

      if "history" not in stock_info:
        stock_info["history"] = []
      stock_info["history"].append(new_price)
      if len(stock_info["history"]) > 24:
        stock_info["history"].pop(0)

      if news_channel:
        embed = discord.Embed(
            title=f"🌙 [야간 장] {stock_name} 소폭 변동",
            description=(
                "야간 시간대에는 부도 및 급등이 정지됩니다.\n\n💵 현재가:"
                f" **{new_price:,}원**"
            ),
            color=0x7289DA,
        )
        await news_channel.send(embed=embed)
    else:
      if stock_name == "SK다우닉스":
        bankruptcy_chance = 5
      elif stock_name == "야멧돼농협":
        bankruptcy_chance = 10
      elif stock_name == "야건식품":
        bankruptcy_chance = 15
      else:
        bankruptcy_chance = 10

      is_bankrupt = random.randint(1, 100) <= bankruptcy_chance

      if is_bankrupt:
        for user_str, user_stocks_dict in data.get("user_stocks", {}).items():
          if stock_name in user_stocks_dict:
            user_stocks_dict[stock_name] = 0

        stock_info["status"] = "bankrupt"
        stock_info["resume_time"] = time.time() + 180
        stock_info["price"] = 1000

        if "history" not in stock_info:
          stock_info["history"] = []
        stock_info["history"].append(1000)
        if len(stock_info["history"]) > 24:
          stock_info["history"].pop(0)

        if news_channel:
          embed = discord.Embed(
              title=f"🚨 [속보] {stock_name} 기업 파산 선고!",
              description=(
                  f"재무 악화로 인해 **{stock_name}**이(가) 결국 **부도**"
                  " 처리되었습니다!\n\n💥 **주주들의 보유 주식과 투자금은 전액"
                  " 손실되었습니다.**\n⏱️ **3분간 거래가 정지**되며, 이후"
                  " 초기가(1,000원)로 재상장됩니다."
              ),
              color=0xFF0000,
          )
          await news_channel.send(embed=embed)
      else:
        increase_rate = random.uniform(0.10, 0.60)
        old_price = stock_info["price"]
        new_price = int(old_price * (1 + increase_rate))
        stock_info["price"] = new_price

        if "history" not in stock_info:
          stock_info["history"] = []
        stock_info["history"].append(new_price)
        if len(stock_info["history"]) > 24:
          stock_info["history"].pop(0)

        if news_channel:
          embed = discord.Embed(
              title=f"📈 [호재] {stock_name} 주가 대폭등!",
              description=(
                  f"대형 호재가 터지며 **{stock_name}** 주가가"
                  f" **+{int(increase_rate * 100)}%** 급등했습니다!\n\n💵"
                  f" 현재가: **{new_price:,}원** (이전가: {old_price:,}원)\n🛡️"
                  f" *현재 부도 위험 확률: {bankruptcy_chance}%*"
              ),
              color=0x00FF00,
          )
          await news_channel.send(embed=embed)

  save_data(data)


@check_reservation_loop.before_loop
async def before_check():
  await bot.wait_until_ready()


@bot.event
async def on_ready():
  print(f"{bot.user.name} 봇이 준비되었습니다!")
  try:
    synced = await bot.tree.sync()
    print(f"성공적으로 {len(synced)}개의 슬러시 명령어(/)를 동기화했습니다!")
  except Exception as e:
    print(f"슬러시 동기화 오류: {e}")

  if not check_reservation_loop.is_running():
    check_reservation_loop.start()


# ==========================================
# 👑 봇 관리자 지정 명령어 (개발자 전용)
# ==========================================
@bot.tree.command(name="봇관리자추가", description="[개발자 전용] 봇 관리자를 추가합니다.")
async def add_bot_admin(interaction: discord.Interaction, member: discord.Member):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **개발자(본인)**만 사용할 수 있습니다!", ephemeral=True
    )
    return

  if member.id in data["bot_admins"]:
    await interaction.response.send_message(
        f"⚠️ {member.mention}님은 이미 봇 관리자입니다."
    )
    return

  data["bot_admins"].append(member.id)
  save_data(data)
  await interaction.response.send_message(
      f"👑 {member.mention}님이 **봇 관리자**로 지정되었습니다!"
  )


@bot.tree.command(name="봇관리자삭제", description="[개발자 전용] 봇 관리자를 해제합니다.")
async def remove_bot_admin(
    interaction: discord.Interaction, member: discord.Member
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **개발자(본인)**만 사용할 수 있습니다!", ephemeral=True
    )
    return

  if member.id not in data["bot_admins"]:
    await interaction.response.send_message(
        f"⚠️ {member.mention}님은 봇 관리자가 아닙니다."
    )
    return

  data["bot_admins"].remove(member.id)
  save_data(data)
  await interaction.response.send_message(
      f"🗑️ {member.mention}님의 **봇 관리자** 권한이 해제되었습니다."
  )


@bot.tree.command(name="봇관리자목록", description="등록된 봇 관리자 목록을 조회합니다.")
async def list_bot_admins(interaction: discord.Interaction):
  admins = data.get("bot_admins", [])
  embed = discord.Embed(title="👑 봇 관리자 목록", color=discord.Color.gold())
  text = f"👑 **서버 소유자**: <@{interaction.guild.owner_id}>\n"
  if admins:
    text += "\n".join([f"• <@{admin_id}>" for admin_id in admins])
  else:
    text += "추가로 지정된 봇 관리자가 없습니다."

  embed.description = text
  await interaction.response.send_message(embed=embed)


# ==========================================
# 🪙 경제 & 포인트 & 상점 & 주식 명령어
# ==========================================
@bot.tree.command(name="출석", description="매일 출석체크하여 10,000P를 지급받습니다.")
async def daily_checkin(interaction: discord.Interaction):
  user_id = interaction.user.id
  user_info = get_user_data(user_id)
  today_str = (datetime.utcnow() + dt_mod.timedelta(hours=9)).strftime(
      "%Y-%m-%d"
  )

  if user_info.get("last_checkin") == today_str:
    await interaction.response.send_message(
        f"❌ {interaction.user.mention}님, 오늘은 이미 출석체크를 완료하셨습니다!"
    )
    return

  reward = 10000
  user_info["last_checkin"] = today_str
  new_bal = update_user_points(user_id, reward)
  await interaction.response.send_message(
      f"📅 **[출석 완료]** {interaction.user.mention}님, 출석 보상으로"
      f" **{reward:,}P** 획득! (현재 잔액: **{new_bal:,}P**)"
  )


@bot.tree.command(name="포인트지급", description="[관리자] 유저에게 포인트를 지급합니다.")
async def give_points(
    interaction: discord.Interaction, member: discord.Member, amount: int
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  new_bal = update_user_points(member.id, amount)
  await interaction.response.send_message(
      f"🪙 {member.mention}님에게 **{amount:,}P**를 지급했습니다. (현재 잔액:"
      f" **{new_bal:,}P**)"
  )


@bot.tree.command(name="포인트차감", description="[관리자] 유저의 포인트를 차감합니다.")
async def remove_points(
    interaction: discord.Interaction, member: discord.Member, amount: int
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  new_bal = update_user_points(member.id, -amount)
  await interaction.response.send_message(
      f"📉 {member.mention}님의 포인트를 **{amount:,}P** 차감했습니다. (현재 잔액:"
      f" **{new_bal:,}P**)"
  )


@bot.tree.command(
    name="포인트확인", description="본인 또는 타인의 포인트 잔액을 확인합니다."
)
async def check_points(
    interaction: discord.Interaction, member: discord.Member = None
):
  target = member or interaction.user
  pts = get_user_points(target.id)
  await interaction.response.send_message(
      f"💳 {target.mention}님의 현재 포인트: **{pts:,}P**"
  )


@bot.tree.command(name="송금", description="유저 간 포인트를 보내줍니다.")
async def transfer_points(
    interaction: discord.Interaction, member: discord.Member, amount: int
):
  if member == interaction.user:
    await interaction.response.send_message(
        "❌ 자신에게는 포인트를 송금할 수 없습니다!"
    )
    return
  if amount <= 0:
    await interaction.response.send_message("❌ 1P 이상부터 송금할 수 있습니다.")
    return

  sender_id = interaction.user.id
  sender_pts = get