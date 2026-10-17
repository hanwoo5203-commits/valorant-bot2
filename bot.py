import asyncio
import datetime
import itertools
import json
import os
import random
from threading import Thread
import discord
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

# --- [2. 디스코드 봇 기본 설정] ---
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
  return {"users": {}, "shop": {}, "user_stocks": {}}


def save_data(data):
  with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)


data = load_data()


def get_user_data(user_id):
  user_str = str(user_id)
  if user_str not in data["users"]:
    data["users"][user_str] = {
        "points": 0,
        "inventory": [],
        "last_checkin": "",  # YYYY-MM-DD 출석 체크용
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


# 5v5 내전 데이터
queue_5v5 = []
is_open_5v5 = False
reserved_time_5v5 = None
reserved_channel_5v5 = None

# 1v1 내전 데이터
queue_1v1 = []
is_open_1v1 = False
last_bracket_embed = None

# ⚽ 피파온라인 내전 데이터
queue_fifa = []
fifa_winners = []
current_tournament_round = 0
last_fifa_group_embed = None
tournament_match_wins = {}
fifa_groups = {}
fifa_stats = {}

# 1v1 유저 전적 데이터
user_wins_1v1 = {}

# 차단 유저 정보
banned_users = {}

# --- 주식 시스템 데이터 (30초마다 변동) ---
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


# ==========================================
# 백그라운드 루프 (예약 및 주식 30초 자동 변동)
# ==========================================
@tasks.loop(seconds=30)
async def check_reservation_loop():
  global is_open_5v5, reserved_time_5v5, reserved_channel_5v5, stock_data

  # 1. 5v5 예약 모집 체크
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
            "🚨 **[5v5 선착순 모집 시작]** 약속된 시간이 되었습니다! 지금부터 `!참가`"
            " 명령어를 입력하세요!"
        )

  # 2. 주식 가격 변동 시스템
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
  if not check_reservation_loop.is_running():
    check_reservation_loop.start()


# ==========================================
# --- [ 신규 경제: 출석, 포인트, 상점, 도박, 주식, 송금, 랭킹 ] ---
# ==========================================
@bot.command(name="출석", aliases=["출석체크", "출체"])
async def daily_checkin(ctx):
  """[일반] 매일 1회 출석하여 10,000 포인트를 획득합니다."""
  user_id = ctx.author.id
  user_info = get_user_data(user_id)

  today_str = (
      datetime.datetime.utcnow() + datetime.timedelta(hours=9)
  ).strftime("%Y-%m-%d")

  if user_info.get("last_checkin") == today_str:
    await ctx.send(
        f"❌ {ctx.author.mention}님, 오늘은 이미 출석체크를 완료하셨습니다! 내일 다시"
        " 시도해 주세요."
    )
    return

  reward = 10000
  user_info["last_checkin"] = today_str
  new_bal = update_user_points(user_id, reward)

  await ctx.send(
      f"📅 **[출석 완료]** {ctx.author.mention}님, 오늘 출석 보상으로"
      f" **{reward:,}P**를 받으셨습니다! 🎉\n현재 잔액: **{new_bal:,}P**"
  )


@bot.command(name="포인트지급")
@commands.has_permissions(administrator=True)
async def give_points(ctx, member: discord.Member, amount: int):
  """[관리자] 유저에게 포인트를 지급합니다."""
  new_bal = update_user_points(member.id, amount)
  await ctx.send(
      f"🪙 {member.mention}님에게 **{amount:,}P**를 지급했습니다. (현재 잔액:"
      f" **{new_bal:,}P**)"
  )


@bot.command(name="포인트차감")
@commands.has_permissions(administrator=True)
async def remove_points(ctx, member: discord.Member, amount: int):
  """[관리자] 유저의 포인트를 차감합니다."""
  new_bal = update_user_points(member.id, -amount)
  await ctx.send(
      f"📉 {member.mention}님의 포인트를 **{amount:,}P** 차감했습니다. (현재 잔액:"
      f" **{new_bal:,}P**)"
  )


@bot.command(name="포인트확인", aliases=["포인트", "잔액", "지갑"])
async def check_points(ctx, member: discord.Member = None):
  """자신 또는 타인의 포인트를 확인합니다."""
  target = member or ctx.author
  pts = get_user_points(target.id)
  await ctx.send(f"💳 {target.mention}님의 현재 포인트: **{pts:,}P**")


@bot.command(name="송금", aliases=["보내기", "포인트보내기"])
async def transfer_points(ctx, member: discord.Member, amount: int):
  """다른 유저에게 포인트를 송금합니다."""
  if member == ctx.author:
    await ctx.send("❌ 자신에게는 포인트를 송금할 수 없습니다!")
    return
  if amount <= 0:
    await ctx.send("❌ 1P 이상부터 송금할 수 있습니다.")
    return

  sender_id = ctx.author.id
  receiver_id = member.id
  sender_pts = get_user_points(sender_id)

  if sender_pts < amount:
    await ctx.send(f"❌ 보유 포인트가 부족합니다! (현재 잔액: **{sender_pts:,}P**)")
    return

  update_user_points(sender_id, -amount)
  update_user_points(receiver_id, amount)

  await ctx.send(
      f"🤝 **[포인트 송금 완료]**\n📤 {ctx.author.mention} ➔ 📥"
      f" {member.mention} : **{amount:,}P** 전달 완료!\n💳 내 남은 잔액:"
      f" **{get_user_points(sender_id):,}P**"
  )


@bot.command(name="전체포인트", aliases=["전체돈", "모든포인트"])
@commands.has_permissions(administrator=True)
async def show_all_users_points(ctx):
  """[관리자] 데이터에 저장된 모든 유저들의 포인트 현황을 조회합니다."""
  users_data = data.get("users", {})
  if not users_data:
    await ctx.send("📊 저장된 유저 포인트 데이터가 없습니다.")
    return

  embed = discord.Embed(
      title="📋 [관리자] 전체 유저 포인트 보유 현황",
      color=discord.Color.dark_gold(),
  )
  text = ""
  for user_str, info in users_data.items():
    user_id = int(user_str)
    pts = info.get("points", 0)
    member = ctx.guild.get_member(user_id)
    name = member.display_name if member else f"유저 ID({user_id})"
    text += f"• **{name}**: {pts:,}P\n"

    if len(text) > 900:
      embed.add_field(name="목록", value=text, inline=False)
      text = ""

  if text:
    embed.add_field(name="목록", value=text, inline=False)

  await ctx.send(embed=embed)


@bot.command(name="부자순위", aliases=["포인트순위", "랭킹"])
async def show_rich_ranking(ctx):
  """서버 내 포인트 부자 순위 TOP 10을 조회합니다."""
  users_data = data.get("users", {})
  if not users_data:
    await ctx.send("📊 아직 등록된 포인트 데이터가 없습니다.")
    return

  user_list = []
  for user_str, info in users_data.items():
    user_list.append((int(user_str), info.get("points", 0)))

  user_list.sort(key=lambda x: x[1], reverse=True)

  embed = discord.Embed(
      title="🏆 서버 포인트 부자 랭킹 (TOP 10)", color=discord.Color.gold()
  )
  rank_text = ""
  for idx, (user_id, pts) in enumerate(user_list[:10], start=1):
    member = ctx.guild.get_member(user_id)
    name = member.display_name if member else f"유저({user_id})"
    medal = (
        "🥇"
        if idx == 1
        else "🥈" if idx == 2 else "🥉" if idx == 3 else f"**{idx}위.**"
    )
    rank_text += f"{medal} {name} - **{pts:,}P**\n"

  embed.add_field(name="💰 자산 순위", value=rank_text, inline=False)
  await ctx.send(embed=embed)


@bot.command(name="상점")
async def show_shop(ctx):
  shop = data.get("shop", {})
  if not shop:
    await ctx.send("🏪 현재 등록된 상점 상품이 없습니다. 관리자에게 문의하세요!")
    return

  embed = discord.Embed(title="🏪 포인트 상점", color=discord.Color.gold())
  for item_name, price in shop.items():
    embed.add_field(
        name=f"📦 {item_name}", value=f"가격: **{price:,}P**", inline=False
    )
  embed.set_footer(text="구매 시 '!구매 [상품명]' 명령어를 사용하세요.")
  await ctx.send(embed=embed)


@bot.command(name="상점추가")
@commands.has_permissions(administrator=True)
async def add_shop_item(ctx, item_name: str, price: int):
  data["shop"][item_name] = price
  save_data(data)
  await ctx.send(
      f"✅ 상점에 **[{item_name}]** (가격: **{price:,}P**) 상품이 추가되었습니다."
  )


@bot.command(name="상점삭제")
@commands.has_permissions(administrator=True)
async def remove_shop_item(ctx, item_name: str):
  if item_name in data["shop"]:
    del data["shop"][item_name]
    save_data(data)
    await ctx.send(f"🗑️ 상점에서 **[{item_name}]** 상품이 삭제되었습니다.")
  else:
    await ctx.send("❌ 해당 상품이 상점에 존재하지 않습니다.")


@bot.command(name="구매")
async def buy_item(ctx, item_name: str):
  shop = data.get("shop", {})
  if item_name not in shop:
    await ctx.send(
        "❌ 해당 상품이 상점에 없습니다. `!상점` 명령어로 확인해 주세요."
    )
    return

  price = shop[item_name]
  user_pts = get_user_points(ctx.author.id)

  if user_pts < price:
    await ctx.send(
        f"❌ 포인트가 부족합니다! (필요 포인트: **{price:,}P** / 보유 포인트:"
        f" **{user_pts:,}P**)"
    )
    return

  update_user_points(ctx.author.id, -price)
  user_str = str(ctx.author.id)
  data["users"][user_str]["inventory"].append(item_name)
  save_data(data)

  await ctx.send(
      f"🎉 {ctx.author.mention}님이 **[{item_name}]**을(를) 성공적으로"
      f" 구매하셨습니다! (차감: **{price:,}P**)"
  )


@bot.command(name="인벤토리", aliases=["가방"])
async def show_inventory(ctx):
  user_str = str(ctx.author.id)
  get_user_points(ctx.author.id)
  inv = data["users"][user_str].get("inventory", [])

  if not inv:
    await ctx.send("🎒 인벤토리가 비어 있습니다.")
    return

  items_str = "\n".join([f"- {item}" for item in inv])
  embed = discord.Embed(
      title=f"🎒 {ctx.author.display_name}님의 인벤토리",
      description=items_str,
      color=discord.Color.blue(),
  )
  await ctx.send(embed=embed)


@bot.command(name="도박", aliases=["주사위"])
async def gamble(ctx, amount: int = None, multiplier: float = 2.0):
  if amount is None or amount <= 0:
    await ctx.send(
        "❌ 올바른 배팅 금액을 입력해주세요! 예: `!도박 1000 2`"
    )
    return

  if multiplier < 1.1 or multiplier > 1000:
    await ctx.send("❌ 배율은 **1.1배 ~ 1000배** 사이로 지정해주세요.")
    return

  user_id = ctx.author.id
  current_pts = get_user_points(user_id)

  if current_pts < amount:
    await ctx.send(
        f"❌ 보유한 포인트보다 많은 금액을 걸 수 없습니다. (현재 잔액:"
        f" **{current_pts:,}P**)"
    )
    return

  win_rate = round(min(80.0, 80.0 / (multiplier**1.6)), 2)
  roll = round(random.uniform(0.01, 100.00), 2)

  if roll <= win_rate:
    profit = int(amount * multiplier) - amount
    new_bal = update_user_points(user_id, profit)
    await ctx.send(
        f"🎲 **[도박 성공!]** 🎉\n🎯 주사위: **{roll}** (당첨 확률: **{win_rate}%**"
        f" 이하)\n🚀 **{multiplier}배율** 성공! `+{profit:,}P` 획득! (현재 잔액:"
        f" **{new_bal:,}P**)"
    )
  else:
    new_bal = update_user_points(user_id, -amount)
    await ctx.send(
        f"🎲 **[도박 실패...]** 💀\n🎯 주사위: **{roll}** (당첨 확률: **{win_rate}%**"
        f" 이하)\n💸 **{amount:,}P**를 잃었습니다. (현재 잔액: **{new_bal:,}P**)"
    )


@bot.command(name="올인")
async def gamble_allin(ctx, multiplier: float = 2.0):
  user_id = ctx.author.id
  pts = get_user_points(user_id)

  if pts <= 0:
    await ctx.send("❌ 올인할 포인트가 없습니다!")
    return

  if multiplier < 1.1 or multiplier > 1000:
    await ctx.send("❌ 배율은 **1.1배 ~ 1000배** 사이로 설정해주세요.")
    return

  win_rate = round(min(80.0, 80.0 / (multiplier**1.6)), 2)
  roll = round(random.uniform(0.01, 100.00), 2)

  if roll <= win_rate:
    profit = int(pts * multiplier) - pts
    new_bal = update_user_points(user_id, profit)
    await ctx.send(
        f"🔥 **[ALL-IN 대성공!!]** 🚀\n🎯 주사위: **{roll}** (당첨 확률:"
        f" **{win_rate}%** 이하)\n👑 **{multiplier}배율** 당첨! 현재 잔액:"
        f" **{new_bal:,}P**"
    )
  else:
    update_user_points(user_id, -pts)
    await ctx.send(
        f"🔥 **[ALL-IN 파산]** 💸\n🎯 주사위: **{roll}** (당첨 확률: **{win_rate}%**"
        " 이하)\n💀 모든 포인트를 잃고 완전히 파산하셨습니다. (현재 잔액: **0P**)"
    )


@bot.command(name="주식시장", aliases=["주식", "증권사"])
async def show_stock_market(ctx):
  embed = discord.Embed(
      title="📈 실시간 포인트 주식 시장",
      description="30초마다 가격이 변동됩니다! (`!주식매수`, `!주식매도`)",
      color=discord.Color.green(),
  )
  for name, info in stock_data.items():
    embed.add_field(
        name=f"🏢 {name}", value=f"현재 가격: **{info['price']:,}P**", inline=False
    )
  await ctx.send(embed=embed)


@bot.command(name="주식매수", aliases=["매수", "주식구매"])
async def buy_stock(ctx, stock_name: str, count: int = 1):
  if stock_name not in stock_data:
    await ctx.send(
        "❌ 존재하지 않는 주식입니다. `!주식시장`에서 종목을 확인해주세요."
    )
    return
  if count <= 0:
    await ctx.send("❌ 1주 이상부터 매수 가능합니다.")
    return

  price = stock_data[stock_name]["price"]
  total_cost = price * count
  user_id = ctx.author.id

  if get_user_points(user_id) < total_cost:
    await ctx.send(
        f"❌ 포인트가 부족합니다! (필요: {total_cost:,}P / 보유:"
        f" {get_user_points(user_id):,}P)"
    )
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

  await ctx.send(
      f"📈 **{stock_name}** {count}주 매수 완료! (총 비용: **{total_cost:,}P**)"
  )


@bot.command(name="주식매도", aliases=["매도", "주식판매"])
async def sell_stock(ctx, stock_name: str, count: int = 1):
  if stock_name not in stock_data:
    await ctx.send("❌ 존재하지 않는 주식입니다.")
    return

  user_id = ctx.author.id
  user_str = str(user_id)
  my_stocks = data.get("user_stocks", {}).get(user_str, {})
  owned = my_stocks.get(stock_name, 0)

  if owned < count:
    await ctx.send(
        f"❌ 보유 중인 주식이 부족합니다! (보유: {owned}주 / 매도 요청:"
        f" {count}주)"
    )
    return

  price = stock_data[stock_name]["price"]
  total_earn = price * count

  data["user_stocks"][user_str][stock_name] -= count
  update_user_points(user_id, total_earn)
  save_data(data)

  await ctx.send(
      f"📉 **{stock_name}** {count}주 매도 완료! (획득 금액: **{total_earn:,}P**)"
  )


@bot.command(name="내주식", aliases=["주식잔고"])
async def my_stock_portfolio(ctx):
  user_str = str(ctx.author.id)
  my_stocks = data.get("user_stocks", {}).get(user_str, {})

  if not my_stocks or all(v == 0 for v in my_stocks.values()):
    await ctx.send("📊 보유 중인 주식이 없습니다.")
    return

  embed = discord.Embed(
      title=f"📊 {ctx.author.display_name}님의 주식 포트폴리오",
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
  await ctx.send(embed=embed)


# =========================================================
# --- [ 5v5 내전 명령어 ] ---
# =========================================================


@bot.command(name="참가")
async def join_5v5(ctx):
  user = ctx.author
  if not is_open_5v5:
    await ctx.send(
        "❌ 아직 5v5 내전 모집이 시작되지 않았습니다! 잠시만 기다려주세요."
    )
    return
  if user.id in banned_users:
    reason = banned_users[user.id]["reason"]
    await ctx.send(
        f"🚫 **{user.display_name}**님은 제재 처리되어 내전에 참가할 수 없습니다.\n사유:"
        f" `{reason}`"
    )
    return
  if user in queue_5v5:
    await ctx.send(f"⚠️ **{user.display_name}**님은 이미 신청하셨습니다.")
    return
  if len(queue_5v5) >= 15:
    await ctx.send("❌ 5v5 대기열이 가득 차서 더 이상 신청할 수 없습니다.")
    return

  queue_5v5.append(user)
  current_count = len(queue_5v5)
  if current_count <= 10:
    await ctx.send(
        f"✅ **{user.display_name}**님 [5v5] 참가 완료! ({current_count}/10명)"
    )
  else:
    reserve_num = current_count - 10
    await ctx.send(
        f"🎟️ **{user.display_name}**님 [5v5] **[예비 {reserve_num}번]**으로"
        " 등록되었습니다!"
    )


@bot.command(name="취소")
async def cancel_5v5(ctx):
  user = ctx.author
  if user not in queue_5v5:
    await ctx.send(f"⚠️ **{user.display_name}**님은 5v5 명단에 없습니다.")
    return
  queue_5v5.remove(user)
  await ctx.send(f"🚫 **{user.display_name}**님의 5v5 참가가 취소되었습니다.")


@bot.command(name="명단")
async def list_5v5(ctx):
  if not queue_5v5:
    await ctx.send("📋 현재 5v5 신청 인원이 없습니다.")
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
  await ctx.send(msg)


@bot.command(name="오픈")
@commands.has_permissions(administrator=True)
async def open_5v5(ctx):
  global is_open_5v5
  is_open_5v5 = True
  await ctx.send(
      "🚨 **[5v5 선착순 모집 시작]** 지금부터 `!참가` 명령어를 사용할 수 있습니다!"
  )


@bot.command(name="예약시간")
@commands.has_permissions(administrator=True)
async def reserve_time_5v5(ctx, time_str: str):
  global reserved_time_5v5, reserved_channel_5v5
  try:
    hour, minute = map(int, time_str.split(":"))
    if not (0 <= hour < 24 and 0 <= minute < 60):
      raise ValueError
    reserved_time_5v5 = f"{hour:02d}:{minute:02d}"
    reserved_channel_5v5 = ctx.channel
    await ctx.send(
        f"⏰ **[5v5 모집 예약 완료]** 오늘 **{reserved_time_5v5}**에 자동으로 모집이"
        " 시작됩니다!"
    )
  except ValueError:
    await ctx.send("⚠️ 올바른 시간 형식이 아닙니다! 예: `!예약시간 15:00`")


@bot.command(name="예약")
@commands.has_permissions(administrator=True)
async def reserve_seconds_5v5(ctx, seconds: int):
  global is_open_5v5
  await ctx.send(
      f"⏳ **{seconds}초 후**에 5v5 모집이 시작됩니다! 준비하세요!"
  )
  await asyncio.sleep(seconds)
  is_open_5v5 = True
  await ctx.send(
      "🚨 **[5v5 선착순 모집 시작]** 지금부터 `!참가` 명령어를 입력하세요!"
  )


@bot.command(name="예약취소")
@commands.has_permissions(administrator=True)
async def cancel_reservation_5v5(ctx):
  global reserved_time_5v5, reserved_channel_5v5
  reserved_time_5v5 = None
  reserved_channel_5v5 = None
  await ctx.send("❌ 5v5 모집 예약이 취소되었습니다.")


@bot.command(name="마감")
@commands.has_permissions(administrator=True)
async def close_5v5(ctx):
  global is_open_5v5
  is_open_5v5 = False
  await ctx.send("🔒 5v5 선착순 모집이 닫혔습니다.")


@bot.command(name="초기화")
@commands.has_permissions(administrator=True)
async def reset_5v5(ctx):
  global queue_5v5, is_open_5v5, reserved_time_5v5, reserved_channel_5v5
  queue_5v5 = []
  is_open_5v5 = False
  reserved_time_5v5 = None
  reserved_channel_5v5 = None
  await ctx.send("🔄 5v5 대기열 및 모집/예약 상태가 초기화되었습니다.")


# =========================================================
# --- [ 1v1 내전 전용 명령어 ] ---
# =========================================================


@bot.command(name="1v1참가")
async def join_1v1(ctx):
  user = ctx.author
  if not is_open_1v1:
    await ctx.send("❌ 아직 1v1 내전 모집이 시작되지 않았습니다!")
    return
  if user.id in banned_users:
    await ctx.send(
        f"🚫 **{user.display_name}**님은 제재 처리되어 참가할 수 없습니다."
    )
    return
  if user in queue_1v1:
    await ctx.send(f"⚠️ **{user.display_name}**님은 이미 신청하셨습니다.")
    return

  queue_1v1.append(user)
  wins = user_wins_1v1.get(user.id, 0)
  tier = get_tier_info(wins)
  await ctx.send(
      f"⚔️ **[{tier}] {user.display_name}**님 [1v1] 참가 완료! (현재"
      f" {len(queue_1v1)}명)"
  )


@bot.command(name="1v1취소")
async def cancel_1v1(ctx):
  user = ctx.author
  if user not in queue_1v1:
    await ctx.send(f"⚠️ **{user.display_name}**님은 1v1 명단에 없습니다.")
    return
  queue_1v1.remove(user)
  await ctx.send(f"🚫 **{user.display_name}**님의 1v1 참가가 취소되었습니다.")


@bot.command(name="1v1명단")
async def list_1v1(ctx):
  if not queue_1v1:
    await ctx.send("📋 현재 1v1 참가자가 없습니다.")
    return
  status_str = "🟢 [모집 중]" if is_open_1v1 else "🔴 [모집 종료/마감]"
  msg = f"📋 **[1v1 참가자 명단 ({len(queue_1v1)}명) - {status_str}]**\n"
  for idx, user in enumerate(queue_1v1, start=1):
    wins = user_wins_1v1.get(user.id, 0)
    tier = get_tier_info(wins)
    msg += f"{idx}. [{tier}] {user.display_name} ({wins}승)\n"
  await ctx.send(msg)


@bot.command(name="1v1전적")
async def stats_1v1(ctx, member: discord.Member = None):
  target = member if member else ctx.author
  wins = user_wins_1v1.get(target.id, 0)
  tier = get_tier_info(wins)
  embed = discord.Embed(
      title=f"📊 {target.display_name} 님의 1v1 전적 정보", color=0x3498DB
  )
  embed.add_field(name="🏆 티어", value=f"**{tier}**", inline=True)
  embed.add_field(name="⚔️ 승리 횟수", value=f"**{wins}승**", inline=True)
  embed.set_thumbnail(url=target.display_avatar.url)
  await ctx.send(embed=embed)


@bot.command(name="1v1순위")
async def rank_1v1(ctx):
  if not user_wins_1v1:
    await ctx.send("📊 기록된 1v1 전적이 없습니다.")
    return
  sorted_ranks = sorted(
      user_wins_1v1.items(), key=lambda item: item[1], reverse=True
  )
  msg = "🏆 **[1v1 랭킹 TOP 5]**\n"
  for idx, (user_id, wins) in enumerate(sorted_ranks[:5], start=1):
    member = ctx.guild.get_member(user_id)
    name = member.display_name if member else f"유저({user_id})"
    tier = get_tier_info(wins)
    msg += f"**{idx}위.** {name} - {tier} ({wins}승)\n"
  await ctx.send(msg)


@bot.command(name="1v1대진표확인")
async def show_bracket_1v1(ctx):
  if last_bracket_embed is None:
    await ctx.send("❌ 아직 생성된 대진표가 없습니다!")
  else:
    await ctx.send(embed=last_bracket_embed)


@bot.command(name="1v1오픈")
@commands.has_permissions(administrator=True)
async def open_1v1(ctx):
  global is_open_1v1
  is_open_1v1 = True
  await ctx.send("⚔️ **[1v1 모집 시작]** `!1v1참가`로 신청하세요!")


@bot.command(name="1v1마감")
@commands.has_permissions(administrator=True)
async def close_1v1(ctx):
  global is_open_1v1
  is_open_1v1 = False
  await ctx.send("🔒 1v1 모집이 닫혔습니다.")


@bot.command(name="1v1대진표")
@commands.has_permissions(administrator=True)
async def make_bracket_1v1(ctx):
  global last_bracket_embed
  if len(queue_1v1) < 2:
    await ctx.send("❌ 최소 2명의 참가자가 필요합니다!")
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
        name="🎁 부전승 (Pass)",
        value=f"[{t_bye}] **{bye_player.display_name}**",
        inline=False,
    )

  last_bracket_embed = embed
  await ctx.send(embed=embed)


@bot.command(name="1v1초기화")
@commands.has_permissions(administrator=True)
async def reset_1v1(ctx):
  global queue_1v1, is_open_1v1, last_bracket_embed
  queue_1v1 = []
  last_bracket_embed = None
  is_open_1v1 = False
  await ctx.send("🔄 1v1 명단 및 대진표가 초기화되었습니다.")


@bot.command(name="1v1승리")
@commands.has_permissions(administrator=True)
async def add_win_1v1(ctx, member: discord.Member):
  current_wins = user_wins_1v1.get(member.id, 0) + 1
  user_wins_1v1[member.id] = current_wins
  await ctx.send(
      f"🎉 **{member.display_name}** 승리 추가! (총"
      f" **{current_wins}승**)"
  )


@bot.command(name="1v1패배")
@commands.has_permissions(administrator=True)
async def remove_win_1v1(ctx, member: discord.Member):
  current_wins = max(0, user_wins_1v1.get(member.id, 0) - 1)
  user_wins_1v1[member.id] = current_wins
  await ctx.send(f"📉 **{member.display_name}** 승수 차감 (총 **{current_wins}승**)")


@bot.command(name="1v1승수설정")
@commands.has_permissions(administrator=True)
async def set_win_1v1(ctx, member: discord.Member, count: int):
  user_wins_1v1[member.id] = max(0, count)
  await ctx.send(f"⚙️ **{member.display_name}** 승수 **{count}승**으로 변경.")


@bot.command(name="1v1전적초기화")
@commands.has_permissions(administrator=True)
async def reset_all_stats_1v1(ctx):
  global user_wins_1v1
  user_wins_1v1 = {}
  await ctx.send("🧹 1v1 전적 및 티어가 초기화되었습니다.")


# =========================================================
# --- [ ⚽ 피파온라인 조별리그(승점) & 토너먼트(3판2승) ] ---
# =========================================================


@bot.command(name="피파추가")
@commands.has_permissions(administrator=True)
async def add_fifa_user(ctx, *, user_input: str = None):
  if not user_input:
    await ctx.send("⚠️ 추가할 유저 이름을 입력해주세요!")
    return
  display_name = (
      ctx.message.mentions[0].display_name
      if ctx.message.mentions
      else user_input
  )
  if display_name in queue_fifa:
    await ctx.send(f"⚠️ **{display_name}**님은 이미 피파 명단에 있습니다.")
    return
  queue_fifa.append(display_name)
  get_or_init_fifa_stat(display_name)
  await ctx.send(
      f"⚽ **{display_name}**님 추가 완료! (현재 **{len(queue_fifa)}명**)"
  )


@bot.command(name="피파제거", aliases=["피파삭제"])
@commands.has_permissions(administrator=True)
async def remove_fifa_user(ctx, *, user_input: str = None):
  if not user_input:
    await ctx.send("⚠️ 제거할 유저 이름을 입력해주세요!")
    return
  display_name = (
      ctx.message.mentions[0].display_name
      if ctx.message.mentions
      else user_input
  )
  if display_name not in queue_fifa:
    await ctx.send(f"⚠️ **{display_name}**님은 명단에 없습니다.")
    return
  queue_fifa.remove(display_name)
  await ctx.send(f"🚫 **{display_name}**님 제거 완료!")


@bot.command(name="피파명단")
async def list_fifa(ctx):
  if not queue_fifa:
    await ctx.send("📋 현재 등록된 참가자가 없습니다.")
    return
  msg = f"⚽ **[피파 명단 (총 {len(queue_fifa)}명)]**\n"
  for idx, name in enumerate(queue_fifa, start=1):
    msg += f"{idx}. {name}\n"
  await ctx.send(msg)


@bot.command(name="피파조배정")
@commands.has_permissions(administrator=True)
async def make_fifa_groups(
    ctx, group_count: int = 2, per_group_count: int = None
):
  global fifa_groups, current_tournament_round
  current_tournament_round = 0

  if not queue_fifa:
    await ctx.send("❌ 피파 참가자 명단이 비어있습니다.")
    return

  shuffled = queue_fifa.copy()
  random.shuffle(shuffled)
  fifa_groups = {}
  group_names = [f"{chr(65 + i)}조" for i in range(group_count)]

  if per_group_count is not None:
    total_needed = group_count * per_group_count
    if len(shuffled) < total_needed:
      await ctx.send(
          f"⚠️ 참가자 수({len(shuffled)}명)가 부족합니다! ({group_count}개 조"
          f" x {per_group_count}명 = 필요 인원 {total_needed}명)"
      )
      return

    for i in range(group_count):
      g_name = group_names[i]
      fifa_groups[g_name] = shuffled[
          i * per_group_count : (i + 1) * per_group_count
      ]
  else:
    for idx, name in enumerate(shuffled):
      g_name = group_names[idx % group_count]
      if g_name not in fifa_groups:
        fifa_groups[g_name] = []
      fifa_groups[g_name].append(name)

  embed = discord.Embed(
      title="🎲 피파온라인 조별리그 조 배정 (승점제)", color=0x2ECC71
  )
  for g_name, members in fifa_groups.items():
    embed.add_field(
        name=f"🏆 {g_name} ({len(members)}명)",
        value="\n".join([f"• {m}" for m in members]),
        inline=True,
    )
  await ctx.send(embed=embed)


@bot.command(name="피파조대진표")
async def show_group_matches(ctx, *, target_group: str = None):
  if not fifa_groups:
    await ctx.send("❌ 먼저 `!피파조배정`으로 조 배정을 진행해주세요.")
    return

  if not target_group:
    await ctx.send("⚠️ 조회할 조 이름을 입력해주세요! 예: `!피파조대진표 A조`")
    return

  if not target_group.endswith("조"):
    target_group += "조"

  if target_group not in fifa_groups:
    await ctx.send(
        f"❌ **{target_group}**를 찾을 수 없습니다. (현재 존재하는 조:"
        f" {', '.join(fifa_groups.keys())})"
    )
    return

  members = fifa_groups[target_group]
  if len(members) < 2:
    await ctx.send(f"⚠️ {target_group}의 인원이 2명 미만이라 대진표를 짜올 수 없습니다.")
    return

  matches = list(itertools.combinations(members, 2))
  embed = discord.Embed(
      title=f"⚽ {target_group} 조별리그 경기 대진표 (풀리그전)",
      description=f"조원 명단: {', '.join(members)}\n총 경기 수: **{len(matches)}경기**",
      color=0x3498DB,
  )

  match_str = ""
  for idx, (p1, p2) in enumerate(matches, start=1):
    match_str += f"**경기 {idx}:** {p1} vs {p2}\n"

  embed.add_field(name="📌 경기 대진 리스트", value=match_str, inline=False)
  await ctx.send(embed=embed)


@bot.command(name="피파조대진표확인")
async def show_all_group_matches(ctx):
  if not fifa_groups:
    await ctx.send("❌ 아직 배정된 조가 없습니다. `!피파조배정`을 먼저 실행해주세요!")
    return

  embed = discord.Embed(
      title="⚽ 전체 조별리그 대진표 (풀리그전)",
      description="모든 조의 경기 일정을 다시 확인합니다.",
      color=0x3498DB,
  )

  for g_name, members in fifa_groups.items():
    if len(members) < 2:
      embed.add_field(
          name=f"📌 {g_name} (인원 부족)",
          value="인원이 2명 미만입니다.",
          inline=False,
      )
      continue

    matches = list(itertools.combinations(members, 2))
    match_str = ""
    for idx, (p1, p2) in enumerate(matches, start=1):
      match_str += f"`경기 {idx}` {p1} vs {p2}\n"

    embed.add_field(
        name=f"🏆 {g_name} ({', '.join(members)})",
        value=match_str,
        inline=False,
    )

  await ctx.send(embed=embed)


@bot.command(name="피파조순위")
async def show_fifa_group_rankings(ctx):
  if not fifa_groups:
    await ctx.send("❌ 먼저 `!피파조배정 [조수]`로 조를 나누어주세요.")
    return

  embed = discord.Embed(
      title="🏆 조별리그 순위표 (승점제)",
      description="정렬: 승점 > 득실차 > 다득점",
      color=0xF1C40F,
  )

  for g_name, members in fifa_groups.items():
    group_stats = []
    for m in members:
      stat = get_or_init_fifa_stat(m)
      group_stats.append((m, stat))

    sorted_stats = sorted(
        group_stats,
        key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]),
        reverse=True,
    )

    rank_str = ""
    for rank, (name, s) in enumerate(sorted_stats, start=1):
      rank_str += (
          f"**{rank}위. {name}** - {s['pts']}점 | {s['win']}승{s['draw']}무{s['loss']}패"
          f" (득실 {s['gd']:+d})\n"
      )

    embed.add_field(name=f"📌 {g_name}", value=rank_str, inline=False)

  await ctx.send(embed=embed)


@bot.command(name="피파결과")
@commands.has_permissions(administrator=True)
async def add_fifa_match_result(
    ctx, p1_name: str, p1_score: int, p2_name: str, p2_score: int
):
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
    res_msg = f"🏆 **{set_winner}** 승리! (승점 +3)" if set_winner else "🤝 **무승부!**"
    embed = discord.Embed(
        title="⚽ 조별리그 경기 결과 기록 완료", description=res_msg, color=0x3498DB
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
    await ctx.send(embed=embed)
    return

  if not set_winner:
    await ctx.send(
        "⚠️ 토너먼트에서는 승부차기 등을 통해 승패가 가려져야 합니다!"
    )
    return

  tournament_match_wins[set_winner] = (
      tournament_match_wins.get(set_winner, 0) + 1
  )

  p1_wins = tournament_match_wins.get(p1_name, 0)
  p2_wins = tournament_match_wins.get(p2_name, 0)

  embed = discord.Embed(
      title=f"⚔️ {current_tournament_round}강 토너먼트 세트 결과 (3판 2선승제)",
      color=0xE74C3C,
  )

  if p1_wins >= 2 or p2_wins >= 2:
    final_winner = p1_name if p1_wins >= 2 else p2_name
    if final_winner not in fifa_winners:
      fifa_winners.append(final_winner)

    embed.description = (
        f"🎉 **{final_winner}**님이 **2승**을 먼저 달성하여 다음 라운드 진출 확정!"
    )
    tournament_match_wins[p1_name] = 0
    tournament_match_wins[p2_name] = 0
  else:
    embed.description = (
        f"🎮 **{set_winner}** 세트 승리! 다음 경기 세트를 계속 진행하세요."
    )

  embed.add_field(
      name=p1_name,
      value=f"이번 세트: {p1_score}점 | 토너먼트 매치 승수: **{p1_wins}승 / 2승**",
  )
  embed.add_field(
      name=p2_name,
      value=f"이번 세트: {p2_score}점 | 토너먼트 매치 승수: **{p2_wins}승 / 2승**",
  )
  await ctx.send(embed=embed)


@bot.command(name="피파진출자", aliases=["피파승자"])
async def list_fifa_winners(ctx):
  if not fifa_winners:
    await ctx.send("📋 아직 기록된 진출자가 없습니다.")
    return
  msg = (
      f"🎟️ **[다음 라운드 진출 확정자 ({len(fifa_winners)}명)]**\n"
      + "\n".join([f"- {name}" for name in fifa_winners])
  )
  await ctx.send(msg)


@bot.command(name="피파토너먼트")
@commands.has_permissions(administrator=True)
async def make_fifa_tournament(ctx, rounds: int = 16):
  global last_fifa_group_embed, current_tournament_round, fifa_winners, tournament_match_wins

  if rounds not in [2, 4, 8, 16, 32]:
    await ctx.send("⚠️ 토너먼트 강수를 올바르게 입력해주세요 (16, 8, 4, 2)")
    return

  current_count = len(queue_fifa)
  if current_count < 2:
    await ctx.send("❌ 최소 2명의 참가자가 필요합니다!")
    return

  fifa_winners = []
  tournament_match_wins = {}
  current_tournament_round = rounds

  shuffled = queue_fifa.copy()
  random.shuffle(shuffled)

  title_map = {
      2: "🏆 결승전 (2강)",
      4: "4강전",
      8: "8강전",
      16: "16강전",
      32: "32강전",
  }
  round_title = title_map.get(rounds, f"{rounds}강전")

  embed = discord.Embed(
      title=f"⚽ 피파온라인 {round_title} 토너먼트 대진표 (3판 2선승제)",
      description=(
          f"총 참가자: **{current_count}명**\n※ 각 매치에서 먼저 2승을 거두는"
          " 유저가 진출합니다!"
      ),
      color=0xE74C3C,
  )

  match_count = rounds // 2
  for i in range(1, match_count + 1):
    p1 = shuffled.pop(0) if shuffled else "BYE (부전승)"
    p2 = shuffled.pop(0) if shuffled else "BYE (부전승)"
    embed.add_field(
        name=f"🎮 {round_title} 매치 {i}",
        value=f"**{p1}** VS **{p2}**",
        inline=False,
    )

  last_fifa_group_embed = embed
  await ctx.send(embed=embed)


@bot.command(name="피파다음라운드")
@commands.has_permissions(administrator=True)
async def make_next_round(ctx):
  global last_fifa_group_embed, current_tournament_round, fifa_winners, tournament_match_wins

  if not fifa_winners:
    await ctx.send("❌ 다음 라운 진출자가 아직 없습니다!")
    return

  if len(fifa_winners) < 2:
    await ctx.send(
        f"🏆 **[최종 우승자]** 축하합니다! **{fifa_winners[0]}**님이 최종"
        " 우승하셨습니다!"
    )
    return

  next_round = current_tournament_round // 2
  current_tournament_round = next_round

  shuffled = fifa_winners.copy()
  fifa_winners = []
  tournament_match_wins = {}
  random.shuffle(shuffled)

  title_map = {2: "🏆 결승전 (2강)", 4: "4강전", 8: "8강전", 16: "16강전"}
  round_title = title_map.get(next_round, f"{next_round}강전")

  embed = discord.Embed(
      title=f"⚽ 피파온라인 {round_title} 대진표 (3판 2선승제)",
      description=f"진출 참가자: **{len(shuffled)}명**",
      color=0xE74C3C,
  )

  match_count = max(1, len(shuffled) // 2)
  for i in range(1, match_count + 1):
    p1 = shuffled.pop(0) if shuffled else "BYE"
    p2 = shuffled.pop(0) if shuffled else "BYE"
    embed.add_field(
        name=f"🎮 {round_title} 매치 {i}",
        value=f"**{p1}** VS **{p2}**",
        inline=False,
    )

  last_fifa_group_embed = embed
  await ctx.send(embed=embed)


@bot.command(name="피파순위", aliases=["피파전적"])
async def show_fifa_rankings(ctx):
  if not fifa_stats:
    await ctx.send("📊 기록된 전적이 없습니다.")
    return
  sorted_stats = sorted(
      fifa_stats.items(),
      key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]),
      reverse=True,
  )
  embed = discord.Embed(
      title="🏆 피파온라인 전체 통합 전적/승점표", color=0xF1C40F
  )
  for rank, (name, s) in enumerate(sorted_stats, start=1):
    detail = (
        f"**{s['pts']}점** | {s['win']}승 {s['draw']}무 {s['loss']}패 | 득실차"
        f" **{s['gd']:+d}** ({s['gf']}득/{s['ga']}실)"
    )
    embed.add_field(name=f"{rank}위. {name}", value=detail, inline=False)
  await ctx.send(embed=embed)


@bot.command(name="피파대진표확인")
async def show_fifa_groups(ctx):
  if last_fifa_group_embed is None:
    await ctx.send("❌ 아직 생성된 대진표가 없습니다!")
  else:
    await ctx.send(embed=last_fifa_group_embed)


@bot.command(name="피파초기화")
@commands.has_permissions(administrator=True)
async def reset_fifa(ctx):
  global queue_fifa, last_fifa_group_embed, fifa_stats, fifa_winners, current_tournament_round, fifa_groups, tournament_match_wins
  queue_fifa = []
  fifa_winners = []
  fifa_groups = {}
  fifa_stats = {}
  tournament_match_wins = {}
  current_tournament_round = 0
  last_fifa_group_embed = None
  await ctx.send("🔄 피파 명단, 전적 및 대진표 데이터가 전체 초기화되었습니다.")


# =========================================================
# --- [ 공통 관리자, 청소 및 차단 기능 ] ---
# =========================================================


@bot.command(name="청소", aliases=["삭제"])
@commands.has_permissions(administrator=True)
async def clear_messages(ctx, count: int = 10):
  if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
    await ctx.send("❌ 메시지 관리 권한이 없습니다!")
    return
  try:
    await ctx.message.delete()
  except Exception:
    pass

  deleted_count = 0
  pinned_messages = await ctx.channel.pins()
  pinned_ids = [m.id for m in pinned_messages]

  async for message in ctx.channel.history(limit=count * 3):
    if message.id not in pinned_ids:
      try:
        await message.delete()
        deleted_count += 1
        await asyncio.sleep(0.4)
      except Exception:
        pass
    if deleted_count >= count:
      break

  notice = await ctx.send(f"🧹 **{deleted_count}개**의 메시지를 정리했습니다!")
  await asyncio.sleep(3)
  try:
    await notice.delete()
  except Exception:
    pass


@bot.command(name="차단")
@commands.has_permissions(administrator=True)
async def ban_user(ctx, member: discord.Member, *, reason: str = None):
  if not reason:
    await ctx.send("⚠️ 차단 사유를 작성해주세요!")
    return
  banned_users[member.id] = {"name": member.display_name, "reason": reason}
  if member in queue_5v5:
    queue_5v5.remove(member)
  if member in queue_1v1:
    queue_1v1.remove(member)
  await ctx.send(
      f"🚫 **{member.display_name}**님 차단 등록 완료. (사유: `{reason}`)"
  )


@bot.command(name="차단해제")
@commands.has_permissions(administrator=True)
async def unban_user(ctx, member: discord.Member):
  if member.id in banned_users:
    del banned_users[member.id]
    await ctx.send(f"✅ **{member.display_name}**님 차단 해제 완료.")
  else:
    await ctx.send("해당 유저는 차단 목록에 없습니다.")


@bot.command(name="차단목록", aliases=["차단내역"])
async def list_banned_users(ctx):
  if not banned_users:
    await ctx.send("✅ 현재 차단된 유저가 없습니다.")
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
  await ctx.send(embed=embed)


@bot.command(name="강퇴")
@commands.has_permissions(administrator=True)
async def kick_user(ctx, member: discord.Member):
  removed = False
  if member in queue_5v5:
    queue_5v5.remove(member)
    removed = True
  if member in queue_1v1:
    queue_1v1.remove(member)
    removed = True

  if removed:
    await ctx.send(f"👋 **{member.display_name}**님을 명단에서 제외했습니다.")
  else:
    await ctx.send("해당 유저는 명단에 없습니다.")


@bot.event
async def on_command_error(ctx, error):
  if isinstance(error, commands.MissingPermissions):
    await ctx.send("❌ 이 명령어는 **서버 관리자**만 사용할 수 있습니다.")


# --- 봇 실행 ---
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
  bot.run(TOKEN)
else:
  print("DISCORD_TOKEN 환경 변수가 설정되지 않았습니다.")