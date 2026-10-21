import asyncio
import datetime
import itertools
import json
import os
import random
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask

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

# --- [2. 디스코드 봇 및 슬러시 명령어 기본 설정] ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- [ 데이터 저장 구조 (JSON) ] ---
DATA_FILE = "data.json"


def load_data():
  if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
      return json.load(f)
  return {"users": {}, "shop": {}, "user_stocks": {}, "bot_admins": [1030754198796632135]}


def save_data(data):
  with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)


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


def is_bot_admin_check(interaction: discord.Interaction) -> bool:
  return (
      interaction.user.id in data.get("bot_admins", [])
      or interaction.user.id == interaction.guild.owner_id
  )


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
    "SK다우닉스": {"price": 300000, "surge_timer": 0},
    "야건식품": {"price": 3000, "surge_timer": 0},
    "야멧돼농협": {"price": 50000, "surge_timer": 0},
}


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


# 백그라운드 루프 (주식 및 예약)
@tasks.loop(seconds=30)
async def check_reservation_loop():
  global is_open_5v5, reserved_time_5v5, reserved_channel_5v5, stock_data

  if reserved_time_5v5 is not None:
    now_kst = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))
    )
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

  sk = stock_data["SK다우닉스"]
  if sk["surge_timer"] > 0:
    sk["surge_timer"] -= 1
    if sk["surge_timer"] == 0:
      sk["price"] = random.randint(280000, 320000)
  else:
    if random.randint(1, 40) == 1:
      sk["price"] = random.randint(200000, 220000)
      sk["surge_timer"] = 3
    else:
      change = random.randint(-4000, 4000)
      sk["price"] = max(180000, min(350000, sk["price"] + change))

  yg = stock_data["야건식품"]
  if yg["surge_timer"] > 0:
    yg["surge_timer"] -= 1
    if yg["surge_timer"] == 0:
      yg["price"] = random.randint(3000, 5000)
  else:
    if random.randint(1, 60) == 1:
      yg["price"] = random.randint(160000, 420000)
      yg["surge_timer"] = 2
    else:
      change = random.randint(-300, 500)
      yg["price"] = max(2000, min(6000, yg["price"] + change))

  ym = stock_data["야멧돼농협"]
  change = random.randint(-15000, 15000)
  ym["price"] = max(10000, min(140000, ym["price"] + change))


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
# 👑 봇 관리자 시스템
# ==========================================
@bot.tree.command(name="봇관리자추가", description="[서버소유자 전용] 봇 관리자를 추가합니다.")
async def add_bot_admin(interaction: discord.Interaction, member: discord.Member):
  if interaction.user.id != interaction.guild.owner_id:
    await interaction.response.send_message(
        "❌ 봇 관리자 추가는 서버 소유자만 가능합니다!", ephemeral=True
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


@bot.tree.command(name="봇관리자삭제", description="[서버소유자 전용] 봇 관리자를 해제합니다.")
async def remove_bot_admin(
    interaction: discord.Interaction, member: discord.Member
):
  if interaction.user.id != interaction.guild.owner_id:
    await interaction.response.send_message(
        "❌ 봇 관리자 해제는 서버 소유자만 가능합니다!", ephemeral=True
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
# 🪙 출석, 포인트, 상점, 송금, 랭킹 시스템
# ==========================================
@bot.tree.command(name="출석", description="매일 1회 출석체크하여 10,000P를 얻습니다.")
async def daily_checkin(interaction: discord.Interaction):
  user_id = interaction.user.id
  user_info = get_user_data(user_id)
  today_str = (
      datetime.datetime.utcnow() + datetime.timedelta(hours=9)
  ).strftime("%Y-%m-%d")

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
        "❌ 이 명령어는 봇 관리자만 사용할 수 있습니다!", ephemeral=True
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
        "❌ 이 명령어는 봇 관리자만 사용할 수 있습니다!", ephemeral=True
    )
    return
  new_bal = update_user_points(member.id, -amount)
  await interaction.response.send_message(
      f"📉 {member.mention}님의 포인트를 **{amount:,}P** 차감했습니다. (현재 잔액:"
      f" **{new_bal:,}P**)"
  )


@bot.tree.command(name="포인트확인", description="포인트를 확인합니다.")
async def check_points(
    interaction: discord.Interaction, member: discord.Member = None
):
  target = member or interaction.user
  pts = get_user_points(target.id)
  await interaction.response.send_message(
      f"💳 {target.mention}님의 현재 포인트: **{pts:,}P**"
  )


@bot.tree.command(name="송금", description="다른 유저에게 포인트를 보내줍니다.")
async def transfer_points(
    interaction: discord.Interaction, member: discord.Member, amount: int
):
  if member == interaction.user:
    await interaction.response.send_message(
        "❌ 자신에게는 송금할 수 없습니다!"
    )
    return
  if amount <= 0:
    await interaction.response.send_message("❌ 1P 이상부터 송금할 수 있습니다.")
    return

  sender_id = interaction.user.id
  if get_user_points(sender_id) < amount:
    await interaction.response.send_message("❌ 보유 포인트가 부족합니다!")
    return

  update_user_points(sender_id, -amount)
  update_user_points(member.id, amount)
  await interaction.response.send_message(
      f"🤝 **[송금 완료]** {interaction.user.mention} ➔ {member.mention} :"
      f" **{amount:,}P** (내 잔액: **{get_user_points(sender_id):,}P**)"
  )


@bot.tree.command(name="전체포인트", description="[관리자] 모든 유저의 포인트 현황을 확인합니다.")
async def show_all_users_points(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 봇 관리자만 접근 가능합니다!", ephemeral=True
    )
    return
  users_data = data.get("users", {})
  embed = discord.Embed(
      title="📋 [관리자] 전체 유저 포인트 현황", color=discord.Color.dark_gold()
  )
  text = ""
  for user_str, info in users_data.items():
    user_id = int(user_str)
    pts = info.get("points", 0)
    member = interaction.guild.get_member(user_id)
    name = member.display_name if member else f"유저 ID({user_id})"
    text += f"• **{name}**: {pts:,}P\n"
    if len(text) > 900:
      embed.add_field(name="목록", value=text, inline=False)
      text = ""
  if text:
    embed.add_field(name="목록", value=text, inline=False)
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="부자순위", description="서버 내 포인트 순위 TOP 10을 조회합니다.")
async def show_rich_ranking(interaction: discord.Interaction):
  users_data = data.get("users", {})
  user_list = [(int(u), info.get("points", 0)) for u, info in users_data.items()]
  user_list.sort(key=lambda x: x[1], reverse=True)

  embed = discord.Embed(
      title="🏆 서버 포인트 부자 랭킹 (TOP 10)", color=discord.Color.gold()
  )
  rank_text = ""
  for idx, (user_id, pts) in enumerate(user_list[:10], start=1):
    member = interaction.guild.get_member(user_id)
    name = member.display_name if member else f"유저({user_id})"
    medal = (
        "🥇"
        if idx == 1
        else "🥈" if idx == 2 else "🥉" if idx == 3 else f"**{idx}위.**"
    )
    rank_text += f"{medal} {name} - **{pts:,}P**\n"
  embed.add_field(name="💰 자산 순위", value=rank_text, inline=False)
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="상점", description="포인트 상점을 엽니다.")
async def show_shop(interaction: discord.Interaction):
  shop = data.get("shop", {})
  if not shop:
    await interaction.response.send_message("🏪 상점이 비어있습니다.")
    return
  embed = discord.Embed(title="🏪 포인트 상점", color=discord.Color.gold())
  for item_name, price in shop.items():
    embed.add_field(
        name=f"📦 {item_name}", value=f"가격: **{price:,}P**", inline=False
    )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="상점추가", description="[관리자] 상점 상품을 등록합니다.")
async def add_shop_item(
    interaction: discord.Interaction, item_name: str, price: int
):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 봇 관리자만 사용 가능합니다!", ephemeral=True
    )
    return
  data["shop"][item_name] = price
  save_data(data)
  await interaction.response.send_message(
      f"✅ **[{item_name}]** ({price:,}P) 상점 추가 완료."
  )


@bot.tree.command(name="구매", description="상점에서 상품을 구매합니다.")
async def buy_item(interaction: discord.Interaction, item_name: str):
  shop = data.get("shop", {})
  if item_name not in shop:
    await interaction.response.send_message("❌ 없는 상품입니다.")
    return
  price = shop[item_name]
  if get_user_points(interaction.user.id) < price:
    await interaction.response.send_message("❌ 포인트 부족!")
    return
  update_user_points(interaction.user.id, -price)
  data["users"][str(interaction.user.id)]["inventory"].append(item_name)
  save_data(data)
  await interaction.response.send_message(
      f"🎉 **[{item_name}]** 구매 완료!"
  )


@bot.tree.command(name="인벤토리", description="내가 보유한 아이템을 확인합니다.")
async def show_inventory(interaction: discord.Interaction):
  inv = (
      data["users"].get(str(interaction.user.id), {}).get("inventory", [])
  )
  if not inv:
    await interaction.response.send_message("🎒 인벤토리가 비어 있습니다.")
    return
  embed = discord.Embed(
      title=f"🎒 {interaction.user.display_name}님의 인벤토리",
      description="\n".join([f"- {i}" for i in inv]),
      color=discord.Color.blue(),
  )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="도박", description="배율 도박을 진행합니다.")
async def gamble(
    interaction: discord.Interaction, amount: int, multiplier: float = 2.0
):
  if amount <= 0 or multiplier < 1.1 or multiplier > 1000:
    await interaction.response.send_message("❌ 잘못된 배팅 조건입니다.")
    return
  user_id = interaction.user.id
  if get_user_points(user_id) < amount:
    await interaction.response.send_message("❌ 포인트 부족!")
    return

  win_rate = round(min(80.0, 80.0 / (multiplier**1.6)), 2)
  roll = round(random.uniform(0.01, 100.00), 2)

  if roll <= win_rate:
    profit = int(amount * multiplier) - amount
    new_bal = update_user_points(user_id, profit)
    await interaction.response.send_message(
        f"🎲 **[도박 성공!]** 🎉 (주사위: {roll} / 기준: {win_rate}%)\n🚀"
        f" **{multiplier}배율** 성공! `+{profit:,}P` (잔액: **{new_bal:,}P**)"
    )
  else:
    new_bal = update_user_points(user_id, -amount)
    await interaction.response.send_message(
        f"🎲 **[도박 실패...]** 💀 (주사위: {roll} / 기준: {win_rate}%)\n💸"
        f" **{amount:,}P** 잃음 (잔액: **{new_bal:,}P**)"
    )


@bot.tree.command(name="주식시장", description="실시간 주식 가격을 확인합니다.")
async def show_stock_market(interaction: discord.Interaction):
  embed = discord.Embed(
      title="📈 실시간 주식 시장", color=discord.Color.green()
  )
  for name, info in stock_data.items():
    embed.add_field(
        name=f"🏢 {name}", value=f"가격: **{info['price']:,}P**", inline=False
    )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="주식매수", description="주식을 사들입니다.")
async def buy_stock(
    interaction: discord.Interaction, stock_name: str, count: int = 1
):
  if stock_name not in stock_data or count <= 0:
    await interaction.response.send_message("❌ 올바른 주식 종목과 수량을 입력하세요.")
    return
  price = stock_data[stock_name]["price"]
  cost = price * count
  user_id = interaction.user.id
  if get_user_points(user_id) < cost:
    await interaction.response.send_message("❌ 포인트 부족!")
    return

  update_user_points(user_id, -cost)
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
      f"📈 **{stock_name}** {count}주 매수 완료! ({cost:,}P)"
  )


@bot.tree.command(name="주식매도", description="보유 주식을 팔아 포인트로 바꿉니다.")
async def sell_stock(
    interaction: discord.Interaction, stock_name: str, count: int = 1
):
  if stock_name not in stock_data:
    await interaction.response.send_message("❌ 존재하지 않는 주식입니다.")
    return
  user_str = str(interaction.user.id)
  owned = data.get("user_stocks", {}).get(user_str, {}).get(stock_name, 0)
  if owned < count:
    await interaction.response.send_message("❌ 주식이 부족합니다!")
    return

  price = stock_data[stock_name]["price"]
  earn = price * count
  data["user_stocks"][user_str][stock_name] -= count
  update_user_points(interaction.user.id, earn)
  save_data(data)
  await interaction.response.send_message(
      f"📉 **{stock_name}** {count}주 매도 완료! (+{earn:,}P)"
  )


@bot.tree.command(name="내주식", description="보유 주식 목록을 조회합니다.")
async def my_stock_portfolio(interaction: discord.Interaction):
  user_str = str(interaction.user.id)
  my_stocks = data.get("user_stocks", {}).get(user_str, {})
  if not my_stocks or all(v == 0 for v in my_stocks.values()):
    await interaction.response.send_message("📊 보유 중인 주식이 없습니다.")
    return

  embed = discord.Embed(
      title=f"📊 {interaction.user.display_name}님의 주식 잔고",
      color=discord.Color.blue(),
  )
  total = 0
  for name, count in my_stocks.items():
    if count > 0:
      val = stock_data[name]["price"] * count
      total += val
      embed.add_field(
          name=f"🏢 {name}", value=f"{count}주 | 평가액: {val:,}P", inline=False
      )
  embed.set_footer(text=f"총 주식 평가액: {total:,}P")
  await interaction.response.send_message(embed=embed)


# ==========================================
# 5v5 / 1v1 / 피파 슬러시 명령어
# ==========================================
@bot.tree.command(name="참가", description="5v5 내전에 참가 신청합니다.")
async def join_5v5(interaction: discord.Interaction):
  user = interaction.user
  if not is_open_5v5:
    await interaction.response.send_message("❌ 5v5 모집이 시작되지 않았습니다!")
    return
  if user.id in banned_users:
    await interaction.response.send_message("🚫 제재 유저는 참가할 수 없습니다.")
    return
  if user in queue_5v5:
    await interaction.response.send_message("⚠️ 이미 신청하셨습니다.")
    return

  queue_5v5.append(user)
  cnt = len(queue_5v5)
  if cnt <= 10:
    await interaction.response.send_message(
        f"✅ {user.display_name}님 5v5 참가 완료! ({cnt}/10명)"
    )
  else:
    await interaction.response.send_message(
        f"🎟️ {user.display_name}님 **[예비 {cnt-10}번]**으로 등록되었습니다!"
    )


@bot.tree.command(name="취소", description="5v5 참가 신청을 취소합니다.")
async def cancel_5v5(interaction: discord.Interaction):
  if interaction.user in queue_5v5:
    queue_5v5.remove(interaction.user)
    await interaction.response.send_message("🚫 참가가 취소되었습니다.")
  else:
    await interaction.response.send_message("⚠️ 신청 명단에 없습니다.")


@bot.tree.command(name="명단", description="5v5 참가 명단을 확인합니다.")
async def list_5v5(interaction: discord.Interaction):
  if not queue_5v5:
    await interaction.response.send_message("📋 신청자가 없습니다.")
    return
  msg = "📋 **[5v5 내전 명단]**\n"
  for idx, user in enumerate(queue_5v5):
    if idx < 10:
      msg += f"{idx + 1}. {user.display_name}\n"
  if len(queue_5v5) > 10:
    msg += "-------------------\n"
    for idx, user in enumerate(queue_5v5[10:], start=1):
      msg += f"예비 {idx}번: {user.display_name}\n"
  await interaction.response.send_message(msg)


@bot.tree.command(name="오픈", description="[관리자] 5v5 내전 모집을 시작합니다.")
async def open_5v5(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 봇 관리자 전용입니다!", ephemeral=True
    )
    return
  global is_open_5v5
  is_open_5v5 = True
  await interaction.response.send_message("🚨 **[5v5 선착순 모집 시작]**")


@bot.tree.command(name="마감", description="[관리자] 5v5 내전 모집을 마감합니다.")
async def close_5v5(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 봇 관리자 전용입니다!", ephemeral=True
    )
    return
  global is_open_5v5
  is_open_5v5 = False
  await interaction.response.send_message("🔒 **[5v5 모집 마감]**")


@bot.tree.command(name="1v1참가", description="1v1 내전에 참가 신청합니다.")
async def join_1v1(interaction: discord.Interaction):
  user = interaction.user
  if not is_open_1v1:
    await interaction.response.send_message("❌ 1v1 모집 중이 아닙니다.")
    return
  if user in queue_1v1:
    await interaction.response.send_message("⚠️ 이미 신청하셨습니다.")
    return
  queue_1v1.append(user)
  wins = user_wins_1v1.get(user.id, 0)
  tier = get_tier_info(wins)
  await interaction.response.send_message(
      f"⚔️ **[{tier}] {user.display_name}**님 1v1 참가 완료!"
  )


@bot.tree.command(name="1v1오픈", description="[관리자] 1v1 모집을 시작합니다.")
async def open_1v1(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 봇 관리자 전용입니다!", ephemeral=True
    )
    return
  global is_open_1v1
  is_open_1v1 = True
  await interaction.response.send_message("⚔️ **[1v1 모집 시작]**")


@bot.tree.command(name="1v1마감", description="[관리자] 1v1 모집을 마감합니다.")
async def close_1v1(interaction: discord.Interaction):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 봇 관리자 전용입니다!", ephemeral=True
    )
    return
  global is_open_1v1
  is_open_1v1 = False
  await interaction.response.send_message("🔒 **[1v1 모집 마감]**")


@bot.tree.command(name="피파추가", description="[관리자] 피파 참가자를 추가합니다.")
async def add_fifa_user(interaction: discord.Interaction, name: str):
  if not is_bot_admin_check(interaction):
    await interaction.response.send_message(
        "❌ 봇 관리자 전용입니다!", ephemeral=True
    )
    return
  if name in queue_fifa:
    await interaction.response.send_message("⚠️ 이미 명단에 있습니다.")
    return
  queue_fifa.append(name)
  get_or_init_fifa_stat(name)
  await interaction.response.send_message(f"⚽ **{name}** 피파 명단 추가 완료!")


@bot.tree.command(name="피파명단", description="피파 참가 명단을 확인합니다.")
async def list_fifa(interaction: discord.Interaction):
  if not queue_fifa:
    await interaction.response.send_message("📋 참가자가 없습니다.")
    return
  msg = "⚽ **[피파 명단]**\n" + "\n".join(
      [f"{idx}. {n}" for idx, n in enumerate(queue_fifa, start=1)]
  )
  await interaction.response.send_message(msg)


# --- 봇 실행 ---
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
  bot.run(TOKEN)
else:
  print("DISCORD_TOKEN 환경 변수가 설정되지 않았습니다.")