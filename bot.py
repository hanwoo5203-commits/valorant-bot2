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

# 각 주식 종목별 기본(최저) 가격
DEFAULT_STOCK_PRICES = {
    "SK다우닉스": 300000,
    "야건식품": 3000,
    "야멧돼농협": 50000,
}

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

  if stock_market_force_closed:
    return

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

        # 부도시 해당 주식의 원래 기준 최저가로 설정
        base_price = DEFAULT_STOCK_PRICES.get(stock_name, 1000)

        stock_info["status"] = "bankrupt"
        stock_info["resume_time"] = time.time() + 180
        stock_info["price"] = base_price

        if "history" not in stock_info:
          stock_info["history"] = []
        stock_info["history"].append(base_price)
        if len(stock_info["history"]) > 24:
          stock_info["history"].pop(0)

        if news_channel:
          embed = discord.Embed(
              title=f"🚨 [속보] {stock_name} 기업 파산 선고!",
              description=(
                  f"재무 악화로 인해 **{stock_name}**이(가) 결국 **부도**"
                  " 처리되었습니다!\n\n💥 **주주들의 보유 주식과 투자금은 전액"
                  " 손실되었습니다.**\n⏱️ **3분간 거래가 정지**되며, 이후"
                  f" 기준 최저가({base_price:,}원)로 재상장됩니다."
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
  if not interaction.guild:
    await interaction.response.send_message("❌ 이 명령어는 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
    return

  admins = data.get("bot_admins", [])
  embed = discord.Embed(title="👑 봇 관리자 목록", color=discord.Color.gold())
  
  owner_id = interaction.guild.owner_id if interaction.guild else "알 수 없음"
  text = f"👑 **서버 소유자**: <@{owner_id}>\n"
  
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
  sender_pts = get_user_points(sender_id)

  if sender_pts < amount:
    await interaction.response.send_message(
        f"❌ 보유 포인트가 부족합니다! (현재 잔액: **{sender_pts:,}P**)"
    )
    return

  update_user_points(sender_id, -amount)
  update_user_points(member.id, amount)
  await interaction.response.send_message(
      f"🤝 **[포인트 송금 완료]**\n📤 {interaction.user.mention} ➔ 📥"
      f" {member.mention} : **{amount:,}P** 전달 완료!\n💳 내 남은 잔액:"
      f" **{get_user_points(sender_id):,}P**"
  )


@bot.tree.command(name="전체포인트", description="[관리자] 전체 유저의 포인트 잔액을 조회합니다.")
async def show_all_users_points(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  users_data = data.get("users", {})
  if not users_data:
    await interaction.response.send_message("📊 저장된 유저 포인트 데이터가 없습니다.")
    return

  embed = discord.Embed(
      title="📋 [관리자] 전체 유저 포인트 보유 현황",
      color=discord.Color.dark_gold(),
  )
  text = ""
  for user_str, info in users_data.items():
    user_id = int(user_str)
    pts = info.get("points", 0)
    member = interaction.guild.get_member(user_id) if interaction.guild else None
    name = member.display_name if member else f"유저 ID({user_id})"
    text += f"• **{name}**: {pts:,}P\n"

    if len(text) > 900:
      embed.add_field(name="목록", value=text, inline=False)
      text = ""

  if text:
    embed.add_field(name="목록", value=text, inline=False)

  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="부자순위", description="서버 포인트 자산 순위 TOP 10을 확인합니다.")
async def show_rich_ranking(interaction: discord.Interaction):
  users_data = data.get("users", {})
  if not users_data:
    await interaction.response.send_message("📊 아직 등록된 포인트 데이터가 없습니다.")
    return

  user_list = [
      (int(user_str), info.get("points", 0))
      for user_str, info in users_data.items()
  ]
  user_list.sort(key=lambda x: x[1], reverse=True)

  embed = discord.Embed(
      title="🏆 서버 포인트 부자 랭킹 (TOP 10)", color=discord.Color.gold()
  )
  rank_text = ""
  for idx, (user_id, pts) in enumerate(user_list[:10], start=1):
    member = interaction.guild.get_member(user_id) if interaction.guild else None
    name = member.display_name if member else f"유저({user_id})"
    medal = (
        "🥇"
        if idx == 1
        else "🥈" if idx == 2 else "🥉" if idx == 3 else f"**{idx}위.**"
    )
    rank_text += f"{medal} {name} - **{pts:,}P**\n"

  embed.add_field(name="💰 자산 순위", value=rank_text, inline=False)
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="상점", description="포인트 상점 상품 목록을 출력합니다.")
async def show_shop(interaction: discord.Interaction):
  shop = data.get("shop", {})
  if not shop:
    await interaction.response.send_message("🏪 현재 등록된 상점 상품이 없습니다.")
    return

  embed = discord.Embed(title="🏪 포인트 상점", color=discord.Color.gold())
  for item_name, price in shop.items():
    embed.add_field(
        name=f"📦 {item_name}", value=f"가격: **{price:,}P**", inline=False
    )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="상점추가", description="[관리자] 상점에 새로운 상품을 추가합니다.")
async def add_shop_item(
    interaction: discord.Interaction, item_name: str, price: int
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  data["shop"][item_name] = price
  save_data(data)
  await interaction.response.send_message(
      f"✅ 상점에 **[{item_name}]** (가격: **{price:,}P**) 상품이 추가되었습니다."
  )


@bot.tree.command(name="상점삭제", description="[관리자] 상점에서 상품을 삭제합니다.")
async def remove_shop_item(interaction: discord.Interaction, item_name: str):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  if item_name in data["shop"]:
    del data["shop"][item_name]
    save_data(data)
    await interaction.response.send_message(
        f"🗑️ 상점에서 **[{item_name}]** 상품이 삭제되었습니다."
    )
  else:
    await interaction.response.send_message("❌ 해당 상품이 상점에 존재하지 않습니다.")


@bot.tree.command(name="구매", description="상점에서 상품을 구매합니다.")
async def buy_item(interaction: discord.Interaction, item_name: str):
  shop = data.get("shop", {})
  if item_name not in shop:
    await interaction.response.send_message("❌ 해당 상품이 상점에 없습니다.")
    return

  price = shop[item_name]
  user_pts = get_user_points(interaction.user.id)

  if user_pts < price:
    await interaction.response.send_message(
        f"❌ 포인트가 부족합니다! (필요: **{price:,}P** / 보유: **{user_pts:,}P**)"
    )
    return

  update_user_points(interaction.user.id, -price)
  user_str = str(interaction.user.id)
  data["users"][user_str]["inventory"].append(item_name)
  save_data(data)

  await interaction.response.send_message(
      f"🎉 {interaction.user.mention}님이 **[{item_name}]**을(를) 구매하셨습니다!"
  )


@bot.tree.command(name="인벤토리", description="내가 보유한 아이템 목록을 봅니다.")
async def show_inventory(interaction: discord.Interaction):
  user_str = str(interaction.user.id)
  inv = data["users"].get(user_str, {}).get("inventory", [])

  if not inv:
    await interaction.response.send_message("🎒 인벤토리가 비어 있습니다.")
    return

  items_str = "\n".join([f"- {item}" for item in inv])
  embed = discord.Embed(
      title=f"🎒 {interaction.user.display_name}님의 인벤토리",
      description=items_str,
      color=discord.Color.blue(),
  )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="도박", description="배율을 설정하고 도박을 진행합니다 (2~9배율).")
async def gamble(
    interaction: discord.Interaction, amount: int, multiplier: int = 2
):
  if amount <= 0:
    await interaction.response.send_message("❌ 올바른 배팅 금액을 입력해주세요!")
    return

  win_rates = {
      2: 44.0,
      3: 30.0,
      4: 19.0,
      5: 5.0,
      6: 2.0,
      7: 1.0,
      8: 0.6,
      9: 0.01,
  }

  if multiplier not in win_rates:
    await interaction.response.send_message(
        "❌ 지원하는 배율은 **2, 3, 4, 5, 6, 7, 8, 9**배율만 가능합니다!"
    )
    return

  user_id = interaction.user.id
  current_pts = get_user_points(user_id)

  if current_pts < amount:
    await interaction.response.send_message("❌ 보유 포인트가 부족합니다!")
    return

  win_rate = win_rates[multiplier]
  roll = round(random.uniform(0.01, 100.00), 2)

  if roll <= win_rate:
    profit = int(amount * multiplier) - amount
    new_bal = update_user_points(user_id, profit)
    await interaction.response.send_message(
        f"🎲 **[도박 성공!]** 🎉 (주사위: {roll} / 기준: {win_rate}% 이하)\n🚀"
        f" **{multiplier}배율** 성공! `+{profit:,}P` 획득! (잔액: **{new_bal:,}P**)"
    )
  else:
    new_bal = update_user_points(user_id, -amount)
    await interaction.response.send_message(
        f"🎲 **[도박 실패...]** 💀 (주사위: {roll} / 기준: {win_rate}% 이하)\n💸"
        f" **{amount:,}P**를 잃었습니다. (잔액: **{new_bal:,}P**)"
    )


@bot.tree.command(name="주식시장", description="실시간 가변 주식 시세를 조회합니다.")
async def show_stock_market(interaction: discord.Interaction):
  embed = discord.Embed(
      title="📈 실시간 포인트 주식 시장",
      description=(
          "1~2시간마다 랜덤 대폭등 및 부도(SK다우닉스 5%, 야멧돼농협 10%,"
          " 야건식품 15%)가 판가름 납니다!"
      ),
      color=discord.Color.green(),
  )
  for name, info in stock_data.items():
    status_msg = (
        "🟢 정상 거래중"
        if info.get("status") != "bankrupt"
        else "🚨 부도 (거래 정지)"
    )
    embed.add_field(
        name=f"🏢 {name}",
        value=(
            f"현재 가격: **{info['price']:,}P**\n상태: `{status_msg}`"
        ),
        inline=False,
    )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="주가", description="지정한 주식의 최근 가격 변동 그래프를 조회합니다.")
async def show_stock_graph(interaction: discord.Interaction, stock_name: str):
  if stock_name not in stock_data:
    await interaction.response.send_message(
        "❌ 존재하지 않는 주식 종목입니다."
    )
    return

  stock_info = stock_data[stock_name]
  history = stock_info.get("history", [stock_info["price"]])

  plt.figure(figsize=(8, 4))
  plt.plot(history, marker="o", color="#5865F2", linewidth=2)
  plt.title(f"{stock_name} Price Trend (Recent Hours)", fontsize=14)
  plt.xlabel("Hours Ago", fontsize=10)
  plt.ylabel("Price (KRW/P)", fontsize=10)
  plt.grid(True, linestyle="--", alpha=0.6)

  buf = io.BytesIO()
  plt.savefig(buf, format="png", bbox_inches="tight")
  buf.seek(0)
  plt.close()

  file = discord.File(buf, filename="stock_graph.png")
  embed = discord.Embed(
      title=f"📊 {stock_name} 주가 차트",
      description=f"현재가: **{stock_info['price']:,}P**",
      color=0x3498DB,
  )
  embed.set_image(url="attachment://stock_graph.png")

  await interaction.response.send_message(file=file, embed=embed)


@bot.tree.command(name="주식매수", description="주식을 지정 수량만큼 매수합니다.")
async def buy_stock(
    interaction: discord.Interaction, stock_name: str, count: int = 1
):
  global stock_market_force_closed

  if stock_market_force_closed:
    await interaction.response.send_message(
        "❌ 현재 관리자에 의해 **주식 시장이 긴급 차단**되어 매수할 수 없습니다!",
        ephemeral=True,
    )
    return

  kst = pytz.timezone("Asia/Seoul")
  current_hour = datetime.now(kst).hour
  if 0 <= current_hour < 7:
    await interaction.response.send_message(
        "❌ **시장 휴장 시간(00:00~07:00)**에는 주식 거래(매수)를 하실 수 없습니다!",
        ephemeral=True,
    )
    return

  if stock_name not in stock_data:
    await interaction.response.send_message("❌ 존재하지 않는 주식입니다.")
    return
  if count <= 0:
    await interaction.response.send_message("❌ 1주 이상부터 매수 가능합니다.")
    return

  stock_info = stock_data[stock_name]
  if stock_info.get("status") == "bankrupt":
    remaining = int(stock_info.get("resume_time", 0) - time.time())
    if remaining > 0:
      await interaction.response.send_message(
          f"⚠️ **{stock_name}** 종목은 현재 부도로 인해 거래 정지 상태입니다!"
          f" (재개까지 약 {remaining // 60}분 {remaining % 60}초 남음)"
      )
      return
    else:
      stock_info["status"] = "normal"

  price = stock_info["price"]
  total_cost = price * count
  user_id = interaction.user.id

  if get_user_points(user_id) < total_cost:
    await interaction.response.send_message("❌ 포인트가 부족합니다!")
    return

  update_user_points(user_id, -total_cost)
  user_str = str(user_id)
  if "user_stocks" not in data:
    data["user_stocks"] = {}
  if user_str not in data["user_stocks"]:
    data["user_stocks"][user_str] = {}

  data["user_stocks"][user_str][stock_name] = (
      data["user_stocks"][user_str].get(stock_name, 0) + count
  )
  save_data(data)

  await interaction.response.send_message(
      f"📈 **{stock_name}** {count}주 매수 완료! (총 비용: **{total_cost:,}P**)"
  )


@bot.tree.command(name="주식매도", description="주식을 지정 수량만큼 매도합니다.")
async def sell_stock(
    interaction: discord.Interaction, stock_name: str, count: int = 1
):
  global stock_market_force_closed

  if stock_market_force_closed:
    await interaction.response.send_message(
        "❌ 현재 관리자에 의해 **주식 시장이 긴급 차단**되어 매도할 수 없습니다!",
        ephemeral=True,
    )
    return

  kst = pytz.timezone("Asia/Seoul")
  current_hour = datetime.now(kst).hour
  if 0 <= current_hour < 7:
    await interaction.response.send_message(
        "❌ **시장 휴장 시간(00:00~07:00)**에는 주식 거래(매도)를 하실 수 없습니다!",
        ephemeral=True,
    )
    return

  if stock_name not in stock_data:
    await interaction.response.send_message("❌ 존재하지 않는 주식입니다.")
    return

  user_id = interaction.user.id
  user_str = str(user_id)
  my_stocks = data.get("user_stocks", {}).get(user_str, {})
  owned = my_stocks.get(stock_name, 0)

  if owned < count:
    await interaction.response.send_message(
        f"❌ 보유 중인 주식이 부족합니다! (보유: {owned}주)"
    )
    return

  price = stock_data[stock_name]["price"]
  total_earn = price * count

  data["user_stocks"][user_str][stock_name] -= count
  update_user_points(user_id, total_earn)
  save_data(data)

  await interaction.response.send_message(
      f"📉 **{stock_name}** {count}주 매도 완료! (획득 금액: **{total_earn:,}P**)"
  )


@bot.tree.command(name="내주식", description="내 보유 주식 포트폴리오를 조회합니다.")
async def my_stock_portfolio(interaction: discord.Interaction):
  user_str = str(interaction.user.id)
  my_stocks = data.get("user_stocks", {}).get(user_str, {})

  if not my_stocks or all(v == 0 for v in my_stocks.values()):
    await interaction.response.send_message("📊 보유 중인 주식이 없습니다.")
    return

  embed = discord.Embed(
      title=f"📊 {interaction.user.display_name}님의 주식 포트폴리오",
      color=discord.Color.blue(),
  )
  total_eval = 0
  for name, count in my_stocks.items():
    if count > 0:
      price = stock_data[name]["price"]
      eval_val = price * count
      total_eval += eval_val
      embed.add_field(
          name=f"🏢 {name}",
          value=(
              f"보유 수량: **{count}주**\n현재 평가금액: **{eval_val:,}P** (1주당"
              f" {price:,}P)"
          ),
          inline=False,
      )
  embed.set_footer(text=f"총 주식 평가액: {total_eval:,}P")
  await interaction.response.send_message(embed=embed)


# ==========================================
# 📈 주식 시장 강제 제어 명령어 (개발자 전용)
# ==========================================
@bot.tree.command(name="주식열기", description="[개발자] 강제 차단되었던 주식 시장을 다시 엽니다.")
async def force_open_stock_market(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **개발자(본인)**만 사용할 수 있습니다!", ephemeral=True
    )
    return

  global stock_market_force_closed
  stock_market_force_closed = False
  await interaction.response.send_message(
      "🟢 **[주식 시장 강제 개방]** 관리자에 의해 주식 시장 거래와 이벤트가"
      " 정상화되었습니다!"
  )


@bot.tree.command(
    name="주식차단", description="[개발자] 주식 시장 거래와 이벤트를 강제로 긴급 차단합니다."
)
async def force_close_stock_market(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **개발자(본인)**만 사용할 수 있습니다!", ephemeral=True
    )
    return

  global stock_market_force_closed
  stock_market_force_closed = True
  await interaction.response.send_message(
      "🚨 **[주식 시장 긴급 차단]** 관리자에 의해 주식 시장 거래와 이벤트가"
      " 강제로 중단되었습니다!"
  )


@bot.tree.command(
    name="주식상태", description="[개발자] 현재 주식 시장의 강제 차단 여부와 상태를 확인합니다."
)
async def check_stock_market_status(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **개발자(본인)**만 사용할 수 있습니다!", ephemeral=True
    )
    return

  global stock_market_force_closed
  status_text = (
      "🔴 **[강제 차단됨]** (거래 및 자동 이벤트 중지)"
      if stock_market_force_closed
      else "🟢 **[정상 운영 중]**"
  )
  embed = discord.Embed(
      title="📊 주식 시장 운영 상태", description=status_text, color=discord.Color.blue()
  )
  await interaction.response.send_message(embed=embed, ephemeral=True)


# ==========================================
# 🎮 5v5 내전 시스템
# ==========================================
@bot.tree.command(name="참가", description="5v5 내전에 참가합니다.")
async def join_5v5(interaction: discord.Interaction):
  user = interaction.user
  if not is_open_5v5:
    await interaction.response.send_message("❌ 아직 5v5 내전 모집이 시작되지 않았습니다!")
    return
  if user.id in banned_users:
    reason = banned_users[user.id]["reason"]
    await interaction.response.send_message(
        f"🚫 제재 처리되어 내전에 참가할 수 없습니다. 사유: `{reason}`"
    )
    return
  if user in queue_5v5:
    await interaction.response.send_message("⚠️ 이미 신청하셨습니다.")
    return
  if len(queue_5v5) >= 15:
    await interaction.response.send_message("❌ 5v5 대기열이 가득 찼습니다.")
    return

  queue_5v5.append(user)
  current_count = len(queue_5v5)
  if current_count <= 10:
    await interaction.response.send_message(
        f"✅ {user.display_name}님 [5v5] 참가 완료! ({current_count}/10명)"
    )
  else:
    await interaction.response.send_message(
        f"🎟️ {user.display_name}님 [5v5] **[예비 {current_count - 10}번]** 등록!"
    )


@bot.tree.command(name="취소", description="5v5 내전 참가를 취소합니다.")
async def cancel_5v5(interaction: discord.Interaction):
  if interaction.user in queue_5v5:
    queue_5v5.remove(interaction.user)
    await interaction.response.send_message(
        f"🚫 {interaction.user.display_name}님의 5v5 참가가 취소되었습니다."
    )
  else:
    await interaction.response.send_message("⚠️ 명단에 없습니다.")


@bot.tree.command(name="명단", description="5v5 참가자 명단을 확인합니다.")
async def list_5v5(interaction: discord.Interaction):
  if not queue_5v5:
    await interaction.response.send_message("📋 현재 5v5 신청 인원이 없습니다.")
    return
  status_str = "🟢 [모집 중]" if is_open_5v5 else "🔴 [모집 종료/마감]"
  msg = f"📋 **[5v5 내전 명단 - {status_str}]**\n"
  for idx, user in enumerate(queue_5v5):
    if idx < 10:
      msg += f"{idx + 1}. {user.display_name}\n"
  if len(queue_5v5) > 10:
    msg += "-------------------\n"
    for idx, user in enumerate(queue_5v5[10:], start=1):
      msg += f"예비 {idx}번: {user.display_name}\n"
  await interaction.response.send_message(msg)


@bot.tree.command(name="오픈", description="[관리자] 5v5 선착순 모집을 즉시 시작합니다.")
async def open_5v5(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global is_open_5v5
  is_open_5v5 = True
  await interaction.response.send_message("🚨 **[5v5 선착순 모집 시작]**")


@bot.tree.command(name="예약시간", description="[관리자] 5v5 모집 시간을 예약합니다 (예: 15:00).")
async def reserve_time_5v5(interaction: discord.Interaction, time_str: str):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global reserved_time_5v5, reserved_channel_5v5
  try:
    hour, minute = map(int, time_str.split(":"))
    if not (0 <= hour < 24 and 0 <= minute < 60):
      raise ValueError
    reserved_time_5v5 = f"{hour:02d}:{minute:02d}"
    reserved_channel_5v5 = interaction.channel
    await interaction.response.send_message(
        f"⏰ 오늘 **{reserved_time_5v5}**에 모집이 자동 시작됩니다!"
    )
  except ValueError:
    await interaction.response.send_message("⚠️ 올바른 형식으로 입력해 주세요. (예: 15:00)")


@bot.tree.command(name="예약", description="[관리자] 지정된 초 후에 5v5 모집을 시작합니다.")
async def reserve_seconds_5v5(interaction: discord.Interaction, seconds: int):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global is_open_5v5
  await interaction.response.send_message(f"⏳ **{seconds}초 후**에 모집이 시작됩니다!")
  await asyncio.sleep(seconds)
  is_open_5v5 = True
  await interaction.channel.send("🚨 **[5v5 선착순 모집 시작]**")


@bot.tree.command(name="예약취소", description="[관리자] 설정된 5v5 예약을 취소합니다.")
async def cancel_reservation_5v5(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global reserved_time_5v5, reserved_channel_5v5
  reserved_time_5v5 = None
  reserved_channel_5v5 = None
  await interaction.response.send_message("❌ 5v5 모집 예약 취소 완료.")


@bot.tree.command(name="마감", description="[관리자] 5v5 모집을 마감합니다.")
async def close_5v5(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global is_open_5v5
  is_open_5v5 = False
  await interaction.response.send_message("🔒 5v5 선착순 모집 마감.")


@bot.tree.command(name="초기화", description="[관리자] 5v5 모집 대기열을 초기화합니다.")
async def reset_5v5(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global queue_5v5, is_open_5v5, reserved_time_5v5, reserved_channel_5v5
  queue_5v5 = []
  is_open_5v5 = False
  reserved_time_5v5 = None
  reserved_channel_5v5 = None
  await interaction.response.send_message("🔄 5v5 대기열 및 상태 초기화 완료.")


# ==========================================
# ⚔️ 1v1 내전 시스템
# ==========================================
@bot.tree.command(name="1v1참가", description="1v1 내전에 참가 신청합니다.")
async def join_1v1(interaction: discord.Interaction):
  user = interaction.user
  if not is_open_1v1:
    await interaction.response.send_message("❌ 아직 1v1 모집이 시작되지 않았습니다!")
    return
  if user.id in banned_users:
    await interaction.response.send_message("🚫 제재 처리되어 참가할 수 없습니다.")
    return
  if user in queue_1v1:
    await interaction.response.send_message("⚠️ 이미 신청하셨습니다.")
    return

  queue_1v1.append(user)
  wins = user_wins_1v1.get(user.id, 0)
  tier = get_tier_info(wins)
  await interaction.response.send_message(
      f"⚔️ **[{tier}] {user.display_name}**님 1v1 참가 완료! ({len(queue_1v1)}명)"
  )


@bot.tree.command(name="1v1취소", description="1v1 참가를 취소합니다.")
async def cancel_1v1(interaction: discord.Interaction):
  if interaction.user in queue_1v1:
    queue_1v1.remove(interaction.user)
    await interaction.response.send_message(
        f"🚫 {interaction.user.display_name}님 1v1 참가 취소."
    )
  else:
    await interaction.response.send_message("⚠️ 명단에 없습니다.")


@bot.tree.command(name="1v1명단", description="1v1 참가 명단을 조회합니다.")
async def list_1v1(interaction: discord.Interaction):
  if not queue_1v1:
    await interaction.response.send_message("📋 현재 1v1 참가자가 없습니다.")
    return
  status_str = "🟢 [모집 중]" if is_open_1v1 else "🔴 [모집 종료]"
  msg = f"📋 **[1v1 참가자 명단 - {status_str}]**\n"
  for idx, user in enumerate(queue_1v1, start=1):
    wins = user_wins_1v1.get(user.id, 0)
    tier = get_tier_info(wins)
    msg += f"{idx}. [{tier}] {user.display_name} ({wins}승)\n"
  await interaction.response.send_message(msg)


@bot.tree.command(name="1v1전적", description="1v1 승수 및 티어를 조회합니다.")
async def stats_1v1(
    interaction: discord.Interaction, member: discord.Member = None
):
  target = member if member else interaction.user
  wins = user_wins_1v1.get(target.id, 0)
  tier = get_tier_info(wins)
  embed = discord.Embed(
      title=f"📊 {target.display_name} 님의 1v1 전적", color=0x3498DB
  )
  embed.add_field(name="🏆 티어", value=f"**{tier}**", inline=True)
  embed.add_field(name="⚔️ 승리 횟수", value=f"**{wins}승**", inline=True)
  embed.set_thumbnail(url=target.display_avatar.url)
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="1v1순위", description="1v1 랭킹 TOP 5를 확인합니다.")
async def rank_1v1(interaction: discord.Interaction):
  if not user_wins_1v1:
    await interaction.response.send_message("📊 기록된 전적이 없습니다.")
    return
  sorted_ranks = sorted(
      user_wins_1v1.items(), key=lambda item: item[1], reverse=True
  )
  msg = "🏆 **[1v1 랭킹 TOP 5]**\n"
  for idx, (user_id, wins) in enumerate(sorted_ranks[:5], start=1):
    member = interaction.guild.get_member(user_id) if interaction.guild else None
    name = member.display_name if member else f"유저({user_id})"
    tier = get_tier_info(wins)
    msg += f"**{idx}위.** {name} - {tier} ({wins}승)\n"
  await interaction.response.send_message(msg)


@bot.tree.command(name="1v1대진표확인", description="마지막으로 생성된 1v1 대진표를 다시 확인합니다.")
async def show_bracket_1v1(interaction: discord.Interaction):
  if last_bracket_embed is None:
    await interaction.response.send_message("❌ 대진표가 없습니다!")
  else:
    await interaction.response.send_message(embed=last_bracket_embed)


@bot.tree.command(name="1v1오픈", description="[관리자] 1v1 내전 모집을 시작합니다.")
async def open_1v1(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global is_open_1v1
  is_open_1v1 = True
  await interaction.response.send_message("⚔️ **[1v1 모집 시작]**")


@bot.tree.command(name="1v1마감", description="[관리자] 1v1 내전 모집을 마감합니다.")
async def close_1v1(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global is_open_1v1
  is_open_1v1 = False
  await interaction.response.send_message("🔒 1v1 모집 마감.")


@bot.tree.command(name="1v1대진표", description="[관리자] 1v1 대진표를 무작위로 생성합니다.")
async def make_bracket_1v1(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global last_bracket_embed
  if len(queue_1v1) < 2:
    await interaction.response.send_message("❌ 최소 2명의 참가자가 필요합니다!")
    return

  shuffled = queue_1v1.copy()
  random.shuffle(shuffled)
  embed = discord.Embed(
      title="⚔️ 1v1 대진표 생성 완료!",
      description=f"총 참가자: **{len(shuffled)}명**",
      color=0xE74C3C,
  )

  match_num = 1
  while len(shuffled) >= 2:
    p1 = shuffled.pop(0)
    p2 = shuffled.pop(0)
    t1 = get_tier_info(user_wins_1v1.get(p1.id, 0))
    t2 = get_tier_info(user_wins_1v1.get(p2.id, 0))
    embed.add_field(
        name=f"🎮 매치 {match_num}",
        value=f"[{t1}] **{p1.display_name}** VS [{t2}] **{p2.display_name}**",
        inline=False,
    )
    match_num += 1

  if shuffled:
    bye_player = shuffled.pop(0)
    t_bye = get_tier_info(user_wins_1v1.get(bye_player.id, 0))
    embed.add_field(
        name="🎁 부전승", value=f"[{t_bye}] **{bye_player.display_name}**", inline=False
    )

  last_bracket_embed = embed
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="1v1초기화", description="[관리자] 1v1 참가 명단과 대진표를 초기화합니다.")
async def reset_1v1(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global queue_1v1, is_open_1v1, last_bracket_embed
  queue_1v1 = []
  last_bracket_embed = None
  is_open_1v1 = False
  await interaction.response.send_message("🔄 1v1 초기화 완료.")


@bot.tree.command(name="1v1승리", description="[관리자] 유저에게 1v1 승수를 1회 부여합니다.")
async def add_win_1v1(
    interaction: discord.Interaction, member: discord.Member
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  current_wins = user_wins_1v1.get(member.id, 0) + 1
  user_wins_1v1[member.id] = current_wins
  await interaction.response.send_message(
      f"🎉 **{member.display_name}** 승리 추가! (총 **{current_wins}승**)"
  )


@bot.tree.command(name="1v1패배", description="[관리자] 유저의 1v1 승수를 1회 차감합니다.")
async def remove_win_1v1(
    interaction: discord.Interaction, member: discord.Member
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  current_wins = max(0, user_wins_1v1.get(member.id, 0) - 1)
  user_wins_1v1[member.id] = current_wins
  await interaction.response.send_message(
      f"📉 **{member.display_name}** 승수 차감 (총 **{current_wins}승**)"
  )


@bot.tree.command(name="1v1승수설정", description="[관리자] 유저의 1v1 승수를 직접 설정합니다.")
async def set_win_1v1(
    interaction: discord.Interaction, member: discord.Member, count: int
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  user_wins_1v1[member.id] = max(0, count)
  await interaction.response.send_message(
      f"⚙️ **{member.display_name}** 승수 **{count}승**으로 변경."
  )


@bot.tree.command(name="1v1전적초기화", description="[관리자] 모든 유저의 1v1 승수를 리셋합니다.")
async def reset_all_stats_1v1(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global user_wins_1v1
  user_wins_1v1 = {}
  await interaction.response.send_message("🧹 1v1 전적 전체 초기화 완료.")


# ==========================================
# ⚽ 피파온라인 내전 시스템
# ==========================================
@bot.tree.command(name="피파추가", description="[관리자] 피파 참가자를 명단에 추가합니다.")
async def add_fifa_user(interaction: discord.Interaction, name: str):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  if name in queue_fifa:
    await interaction.response.send_message("⚠️ 이미 명단에 있습니다.")
    return
  queue_fifa.append(name)
  get_or_init_fifa_stat(name)
  await interaction.response.send_message(
      f"⚽ **{name}** 추가 완료! ({len(queue_fifa)}명)"
  )


@bot.tree.command(name="피파제거", description="[관리자] 피파 참가자를 명단에서 삭제합니다.")
async def remove_fifa_user(interaction: discord.Interaction, name: str):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  if name not in queue_fifa:
    await interaction.response.send_message("⚠️ 명단에 없습니다.")
    return
  queue_fifa.remove(name)
  await interaction.response.send_message(f"🚫 **{name}** 제거 완료.")


@bot.tree.command(name="피파명단", description="피파 참가 명단을 조회합니다.")
async def list_fifa(interaction: discord.Interaction):
  if not queue_fifa:
    await interaction.response.send_message("📋 등록된 참가자가 없습니다.")
    return
  msg = f"⚽ **[피파 명단 ({len(queue_fifa)}명)]**\n"
  for idx, name in enumerate(queue_fifa, start=1):
    msg += f"{idx}. {name}\n"
  await interaction.response.send_message(msg)


@bot.tree.command(name="피파조배정", description="[관리자] 조별리그 조 배정을 실행합니다.")
async def make_fifa_groups(
    interaction: discord.Interaction,
    group_count: int = 2,
    per_group_count: int = None,
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global fifa_groups, current_tournament_round
  current_tournament_round = 0
  if not queue_fifa:
    await interaction.response.send_message("❌ 피파 참가자 명단이 비어있습니다.")
    return

  shuffled = queue_fifa.copy()
  random.shuffle(shuffled)
  fifa_groups = {}
  group_names = [f"{chr(65 + i)}조" for i in range(group_count)]

  if per_group_count is not None:
    total_needed = group_count * per_group_count
    if len(shuffled) < total_needed:
      await interaction.response.send_message("⚠️ 참가자 수가 부족합니다!")
      return
    for i in range(group_count):
      fifa_groups[group_names[i]] = shuffled[
          i * per_group_count : (i + 1) * per_group_count
      ]
  else:
    for idx, name in enumerate(shuffled):
      g_name = group_names[idx % group_count]
      if g_name not in fifa_groups:
        fifa_groups[g_name] = []
      fifa_groups[g_name].append(name)

  embed = discord.Embed(
      title="🎲 피파온라인 조별리그 조 배정", color=0x2ECC71
  )
  for g_name, members in fifa_groups.items():
    embed.add_field(
        name=f"🏆 {g_name} ({len(members)}명)",
        value="\n".join([f"• {m}" for m in members]),
        inline=True,
    )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="피파조대진표", description="특정 조의 리그 대진표를 확인합니다 (예: A조).")
async def show_group_matches(
    interaction: discord.Interaction, target_group: str
):
  if not fifa_groups:
    await interaction.response.send_message("❌ 조가 구성되지 않았습니다.")
    return
  if not target_group.endswith("조"):
    target_group += "조"

  if target_group not in fifa_groups:
    await interaction.response.send_message("❌ 해당 조를 찾을 수 없습니다.")
    return

  members = fifa_groups[target_group]
  matches = list(itertools.combinations(members, 2))
  embed = discord.Embed(
      title=f"⚽ {target_group} 조별리그 대진표", color=0x3498DB
  )
  match_str = "\n".join(
      [f"**경기 {idx}:** {p1} vs {p2}" for idx, (p1, p2) in enumerate(matches, 1)]
  )
  embed.add_field(name="📌 경기 일정", value=match_str, inline=False)
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="피파조대진표확인", description="전체 조의 리그 대진표를 확인합니다.")
async def show_all_group_matches(interaction: discord.Interaction):
  if not fifa_groups:
    await interaction.response.send_message("❌ 배정된 조가 없습니다.")
    return
  embed = discord.Embed(title="⚽ 전체 조별리그 대진표", color=0x3498DB)
  for g_name, members in fifa_groups.items():
    if len(members) >= 2:
      matches = list(itertools.combinations(members, 2))
      match_str = "\n".join(
          [f"`경기 {idx}` {p1} vs {p2}" for idx, (p1, p2) in enumerate(matches, 1)]
      )
      embed.add_field(
          name=f"🏆 {g_name} ({', '.join(members)})",
          value=match_str,
          inline=False,
      )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="피파조순위", description="조별리그 순위표를 확인합니다.")
async def show_fifa_group_rankings(interaction: discord.Interaction):
  if not fifa_groups:
    await interaction.response.send_message("❌ 먼저 조를 나누어주세요.")
    return

  embed = discord.Embed(title="🏆 조별리그 순위표", color=0xF1C40F)
  for g_name, members in fifa_groups.items():
    group_stats = [(m, get_or_init_fifa_stat(m)) for m in members]
    sorted_stats = sorted(
        group_stats,
        key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]),
        reverse=True,
    )
    rank_str = "\n".join([
        f"**{r}위. {n}** - {s['pts']}점 | {s['win']}승{s['draw']}무{s['loss']}패"
        f" (득실 {s['gd']:+d})"
        for r, (n, s) in enumerate(sorted_stats, 1)
    ])
    embed.add_field(name=f"📌 {g_name}", value=rank_str, inline=False)
  await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="피파결과", description="[관리자] 피파 경기 결과를 입력합니다 (선수1, 점수1, 선수2, 점수2)."
)
async def add_fifa_match_result(
    interaction: discord.Interaction,
    p1_name: str,
    p1_score: int,
    p2_name: str,
    p2_score: int,
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global fifa_winners, tournament_match_wins
  p1_stat = get_or_init_fifa_stat(p1_name)
  p2_stat = get_or_init_fifa_stat(p2_name)

  p1_stat["gf"] += p1_score
  p1_stat["ga"] += p2_score
  p1_stat["gd"] = p1_stat["gf"] - p1_stat["ga"]
  p2_stat["gf"] += p2_score
  p2_stat["ga"] += p1_score
  p2_stat["gd"] = p2_stat["gf"] - p2_stat["ga"]

  set_winner = None
  if p1_score > p2_score:
    p1_stat["win"] += 1
    p1_stat["pts"] += 3
    p2_stat["loss"] += 1
    set_winner = p1_name
  elif p2_score > p1_score:
    p2_stat["win"] += 1
    p2_stat["pts"] += 3
    p1_stat["loss"] += 1
    set_winner = p2_name
  else:
    p1_stat["draw"] += 1
    p1_stat["pts"] += 1
    p2_stat["draw"] += 1
    p2_stat["pts"] += 1

  if current_tournament_round == 0:
    res_msg = f"🏆 **{set_winner}** 승리! (승점 +3)" if set_winner else "🤝 무승부!"
    embed = discord.Embed(
        title="⚽ 경기 결과 기록 완료", description=res_msg, color=0x3498DB
    )
    embed.add_field(
        name=p1_name,
        value=(
            f"득점: {p1_score} | 누적:"
            f" {p1_stat['pts']}점({p1_stat['win']}승{p1_stat['draw']}무{p1_stat['loss']}패)"
        ),
    )
    embed.add_field(
        name=p2_name,
        value=(
            f"득점: {p2_score} | 누적:"
            f" {p2_stat['pts']}점({p2_stat['win']}승{p2_stat['draw']}무{p2_stat['loss']}패)"
        ),
    )
    await interaction.response.send_message(embed=embed)
    return

  if not set_winner:
    await interaction.response.send_message("⚠️ 토너먼트에서는 승패가 가려져야 합니다!")
    return

  tournament_match_wins[set_winner] = (
      tournament_match_wins.get(set_winner, 0) + 1
  )
  p1_wins = tournament_match_wins.get(p1_name, 0)
  p2_wins = tournament_match_wins.get(p2_name, 0)

  embed = discord.Embed(
      title=f"⚔️ {current_tournament_round}강 토너먼트 세트 결과", color=0xE74C3C
  )
  if p1_wins >= 2 or p2_wins >= 2:
    final_winner = p1_name if p1_wins >= 2 else p2_name
    if final_winner not in fifa_winners:
      fifa_winners.append(final_winner)
    embed.description = f"🎉 **{final_winner}**님 다음 라운드 진출 확정!"
    tournament_match_wins[p1_name] = 0
    tournament_match_wins[p2_name] = 0
  else:
    embed.description = f"🎮 **{set_winner}** 세트 승리!"

  embed.add_field(
      name=p1_name,
      value=f"이번: {p1_score}점 | 토너먼트 승수: **{p1_wins}승 / 2승**",
  )
  embed.add_field(
      name=p2_name,
      value=f"이번: {p2_score}점 | 토너먼트 승수: **{p2_wins}승 / 2승**",
  )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="피파진출자", description="토너먼트 다음 라운드 진출자 목록을 확인합니다.")
async def list_fifa_winners(interaction: discord.Interaction):
  if not fifa_winners:
    await interaction.response.send_message("📋 기록된 진출자가 없습니다.")
    return
  await interaction.response.send_message(
      "🎟️ **[진출 확정자]**\n" + "\n".join([f"- {name}" for name in fifa_winners])
  )


@bot.tree.command(name="피파토너먼트", description="[관리자] 피파 토너먼트 대진표를 생성합니다.")
async def make_fifa_tournament(
    interaction: discord.Interaction, rounds: int = 16
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global last_fifa_group_embed, current_tournament_round, fifa_winners, tournament_match_wins
  if rounds not in [2, 4, 8, 16, 32] or len(queue_fifa) < 2:
    await interaction.response.send_message("⚠️ 조건이 맞지 않습니다.")
    return

  fifa_winners = []
  tournament_match_wins = {}
  current_tournament_round = rounds
  shuffled = queue_fifa.copy()
  random.shuffle(shuffled)

  embed = discord.Embed(
      title=f"⚽ 피파온라인 {rounds}강 토너먼트 대진표 (3판 2선승)",
      color=0xE74C3C,
  )
  for i in range(1, rounds // 2 + 1):
    p1 = shuffled.pop(0) if shuffled else "BYE"
    p2 = shuffled.pop(0) if shuffled else "BYE"
    embed.add_field(
        name=f"🎮 매치 {i}", value=f"**{p1}** VS **{p2}**", inline=False
    )

  last_fifa_group_embed = embed
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="피파다음라운드", description="[관리자] 토너먼트 승자들로 다음 라운드 대진표를 짜줍니다.")
async def make_next_round(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global last_fifa_group_embed, current_tournament_round, fifa_winners, tournament_match_wins
  if not fifa_winners:
    await interaction.response.send_message("❌ 진출자가 없습니다!")
    return
  if len(fifa_winners) < 2:
    await interaction.response.send_message(
        f"🏆 **[최종 우승자]** **{fifa_winners[0]}**님 축하합니다!"
    )
    return

  next_round = current_tournament_round // 2
  current_tournament_round = next_round
  shuffled = fifa_winners.copy()
  fifa_winners = []
  tournament_match_wins = {}
  random.shuffle(shuffled)

  embed = discord.Embed(
      title=f"⚽ 피파온라인 {next_round}강 대진표", color=0xE74C3C
  )
  for i in range(1, max(1, len(shuffled) // 2) + 1):
    p1 = shuffled.pop(0) if shuffled else "BYE"
    p2 = shuffled.pop(0) if shuffled else "BYE"
    embed.add_field(
        name=f"🎮 매치 {i}", value=f"**{p1}** VS **{p2}**", inline=False
    )

  last_fifa_group_embed = embed
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="피파순위", description="피파 통합 전적/승점표를 출력합니다.")
async def show_fifa_rankings(interaction: discord.Interaction):
  if not fifa_stats:
    await interaction.response.send_message("📊 기록된 전적이 없습니다.")
    return
  sorted_stats = sorted(
      fifa_stats.items(),
      key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]),
      reverse=True,
  )
  embed = discord.Embed(title="🏆 피파온라인 통합 전적/승점표", color=0xF1C40F)
  for rank, (name, s) in enumerate(sorted_stats, 1):
    embed.add_field(
        name=f"{rank}위. {name}",
        value=(
            f"**{s['pts']}점** | {s['win']}승 {s['draw']}무 {s['loss']}패 | 득실"
            f" **{s['gd']:+d}**"
        ),
        inline=False,
    )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="피파대진표확인", description="마지막 피파 토너먼트 대진표를 확인합니다.")
async def show_fifa_groups(interaction: discord.Interaction):
  if last_fifa_group_embed is None:
    await interaction.response.send_message("❌ 생성된 대진표가 없습니다!")
  else:
    await interaction.response.send_message(embed=last_fifa_group_embed)


@bot.tree.command(name="피파초기화", description="[관리자] 피파 관련 모든 데이터를 리셋합니다.")
async def reset_fifa(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  global queue_fifa, last_fifa_group_embed, fifa_stats, fifa_winners, current_tournament_round, fifa_groups, tournament_match_wins
  queue_fifa = []
  fifa_winners = []
  fifa_groups = {}
  fifa_stats = {}
  tournament_match_wins = {}
  current_tournament_round = 0
  last_fifa_group_embed = None
  await interaction.response.send_message("🔄 피파 데이터 전체 초기화 완료.")


# ==========================================
# 🛠️ 서버 관리 & 제재 명령어
# ==========================================
@bot.tree.command(name="청소", description="[관리자] 지정한 수만큼 채팅 메시지를 삭제합니다.")
async def clear_messages(interaction: discord.Interaction, count: int = 10):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  await interaction.response.defer(ephemeral=True)
  deleted_count = 0
  pinned_messages = await interaction.channel.pins()
  pinned_ids = [m.id for m in pinned_messages]

  async for message in interaction.channel.history(limit=count * 3):
    if message.id not in pinned_ids:
      try:
        await message.delete()
        deleted_count += 1
        await asyncio.sleep(0.4)
      except Exception:
        pass
    if deleted_count >= count:
      break

  await interaction.followup.send(
      f"🧹 **{deleted_count}개**의 메시지를 정리했습니다!", ephemeral=True
  )


@bot.tree.command(name="차단", description="[관리자] 유저를 내전 참가 불가 목록에 추가합니다.")
async def ban_user(
    interaction: discord.Interaction, member: discord.Member, reason: str
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  banned_users[member.id] = {"name": member.display_name, "reason": reason}
  if member in queue_5v5:
    queue_5v5.remove(member)
  if member in queue_1v1:
    queue_1v1.remove(member)
  await interaction.response.send_message(
      f"🚫 **{member.display_name}**님 차단 등록 완료. (사유: `{reason}`)"
  )


@bot.tree.command(name="차단해제", description="[관리자] 유저의 내전 차단을 해제합니다.")
async def unban_user(
    interaction: discord.Interaction, member: discord.Member
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  if member.id in banned_users:
    del banned_users[member.id]
    await interaction.response.send_message(
        f"✅ **{member.display_name}**님 차단 해제 완료."
    )
  else:
    await interaction.response.send_message("해당 유저는 차단 목록에 없습니다.")


@bot.tree.command(name="차단목록", description="현재 내전 차단된 유저 목록을 봅니다.")
async def list_banned_users(interaction: discord.Interaction):
  if not banned_users:
    await interaction.response.send_message("✅ 현재 차단된 유저가 없습니다.")
    return
  embed = discord.Embed(
      title="🚫 차단 유저 목록", description=f"총 {len(banned_users)}명", color=0x8B0000
  )
  for user_id, info in banned_users.items():
    embed.add_field(
        name=f"👤 {info['name']} ({user_id})",
        value=f"📄 사유: {info['reason']}",
        inline=False,
    )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="강퇴", description="[관리자] 유저를 내전 명단에서 강제로 제외합니다.")
async def kick_user(
    interaction: discord.Interaction, member: discord.Member
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 이 명령어는 **봇 관리자**만 사용할 수 있습니다!", ephemeral=True
    )
    return
  removed = False
  if member in queue_5v5:
    queue_5v5.remove(member)
    removed = True
  if member in queue_1v1:
    queue_1v1.remove(member)
    removed = True

  if removed:
    await interaction.response.send_message(
        f"👋 **{member.display_name}**님을 명단에서 제외했습니다."
    )
  else:
    await interaction.response.send_message("해당 유저는 명단에 없습니다.")


# --- 봇 실행 ---
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
  bot.run(TOKEN)
else:
  print("DISCORD_TOKEN 환경 변수가 설정되지 않았습니다.")