import asyncio
import datetime
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
bot = commands.Bot(command_prefix="!", intents=intents)

# --- [ 데이터 저장 구조 ] ---
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
queue_fifa = []  # 등록된 전체 유저 명단
fifa_winners = []  # 현재 토너먼트 라운드 승자 명단 (다음 라운드 진출자)
current_tournament_round = 0  # 현재 진행 중인 강수 (예: 8, 4, 2)
last_fifa_group_embed = None  # 최근 대진표 임베드

# ⚽ 피파온라인 유저별 전적/득실차 데이터
# { "유저이름": {"win": 0, "draw": 0, "loss": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0} }
fifa_stats = {}

# 1v1 유저 전적 저장 데이터 { user_id: win_count }
user_wins_1v1 = {}

# 차단 유저 정보 { user_id: {"name": str, "reason": str} }
banned_users = {}


# --- [ Helper 함수: 1v1 승수 기반 티어 계산 ] ---
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


# --- [ Helper 함수: 피파 유저 전적 초기화/가져오기 ] ---
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


# --- [ 백그라운드 예약 시각 체크 루프 ] ---
@tasks.loop(seconds=30)
async def check_reservation_loop():
  global is_open_5v5, reserved_time_5v5, reserved_channel_5v5
  if reserved_time_5v5 is None:
    return

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


@check_reservation_loop.before_loop
async def before_check():
  await bot.wait_until_ready()


@bot.event
async def on_ready():
  print(f"{bot.user.name} 봇이 준비되었습니다!")
  if not check_reservation_loop.is_running():
    check_reservation_loop.start()


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
    await ctx.send(
        "❌ 5v5 대기열이 가득 차서 더 이상 신청할 수 없습니다. (최대 15명: 주전"
        " 10명 + 예비 5명)"
    )
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
    await ctx.send("⚠️ 올바른 시간 형식이 아닙니다! 예: `!예약시간 15:00` (24시간제)")


@bot.command(name="예약")
@commands.has_permissions(administrator=True)
async def reserve_seconds_5v5(ctx, seconds: int):
  global is_open_5v5
  if seconds > 3600:
    await ctx.send(
        "⚠️ 1시간(3600초) 이상의 긴 예약은 `!예약시간 HH:MM` 명령어를 사용하는 것이"
        " 안전합니다!"
    )

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
# --- [ 1v1 내전 전용 명령어 및 개인 대진표 시스템 ] ---
# =========================================================


@bot.command(name="1v1참가")
async def join_1v1(ctx):
  user = ctx.author

  if not is_open_1v1:
    await ctx.send(
        "❌ 아직 1v1 내전 모집이 시작되지 않았습니다! 잠시만 기다려주세요."
    )
    return

  if user.id in banned_users:
    reason = banned_users[user.id]["reason"]
    await ctx.send(
        f"🚫 **{user.display_name}**님은 제재 처리되어 내전에 참가할 수 없습니다.\n사유:"
        f" `{reason}`"
    )
    return

  if user in queue_1v1:
    await ctx.send(f"⚠️ **{user.display_name}**님은 이미 참가 신청하셨습니다.")
    return

  queue_1v1.append(user)
  current_count = len(queue_1v1)

  wins = user_wins_1v1.get(user.id, 0)
  tier = get_tier_info(wins)

  await ctx.send(
      f"⚔️ **[{tier}] {user.display_name}**님 [1v1] 참가 완료!"
      f" (현재 참가자: {current_count}명)"
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
    await ctx.send(
        "❌ 아직 생성된 대진표가 없습니다! 관리자에게 `!1v1대진표`를 요청하세요."
    )
  else:
    await ctx.send(embed=last_bracket_embed)


@bot.command(name="1v1오픈")
@commands.has_permissions(administrator=True)
async def open_1v1(ctx):
  global is_open_1v1
  is_open_1v1 = True
  await ctx.send(
      "⚔️ **[1v1 모집 시작]** 지금부터 `!1v1참가` 명령어로 신청할 수 있습니다!"
  )


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
    await ctx.send("❌ 대진표를 만들려면 최소 2명의 참가자가 필요합니다!")
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
  await ctx.send("🔄 1v1 참가자 명단 및 대진표가 초기화되었습니다.")


@bot.command(name="1v1승리")
@commands.has_permissions(administrator=True)
async def add_win_1v1(ctx, member: discord.Member):
  current_wins = user_wins_1v1.get(member.id, 0) + 1
  user_wins_1v1[member.id] = current_wins
  tier = get_tier_info(current_wins)
  await ctx.send(
      f"🎉 **{member.display_name}**님에게 1v1 승리가 추가되었습니다! (총"
      f" **{current_wins}승** | 티어: **{tier}**)"
  )


@bot.command(name="1v1패배")
@commands.has_permissions(administrator=True)
async def remove_win_1v1(ctx, member: discord.Member):
  current_wins = max(0, user_wins_1v1.get(member.id, 0) - 1)
  user_wins_1v1[member.id] = current_wins
  tier = get_tier_info(current_wins)
  await ctx.send(
      f"📉 **{member.display_name}**님의 1v1 승수가 차감되었습니다. (총"
      f" **{current_wins}승** | 티어: **{tier}**)"
  )


@bot.command(name="1v1승수설정")
@commands.has_permissions(administrator=True)
async def set_win_1v1(ctx, member: discord.Member, count: int):
  count = max(0, count)
  user_wins_1v1[member.id] = count
  tier = get_tier_info(count)
  await ctx.send(
      f"⚙️ **{member.display_name}**님의 1v1 승수가 **{count}승**으로 변경되었습니다."
      f" (티어: **{tier}**)"
  )


@bot.command(name="1v1전적초기화")
@commands.has_permissions(administrator=True)
async def reset_all_stats_1v1(ctx):
  global user_wins_1v1
  user_wins_1v1 = {}
  await ctx.send("🧹 모든 유저의 1v1 전적 및 티어 정보가 초기화되었습니다.")


# =========================================================
# --- [ ⚽ 피파온라인 토너먼트 & 승자 자동 진출 시스템 ] ---
# =========================================================


@bot.command(name="피파추가")
@commands.has_permissions(administrator=True)
async def add_fifa_user(ctx, *, user_input: str = None):
  """관리자가 명단에 유저를 추가합니다 (멘션 또는 이름 가능)"""
  if not user_input:
    await ctx.send("⚠️ 추가할 유저 이름을 입력해주세요! 예: `!피파추가 손흥민`")
    return

  display_name = user_input
  if ctx.message.mentions:
    display_name = ctx.message.mentions[0].display_name

  if display_name in queue_fifa:
    await ctx.send(f"⚠️ **{display_name}**님은 이미 피파 명단에 있습니다.")
    return

  queue_fifa.append(display_name)
  get_or_init_fifa_stat(display_name)
  await ctx.send(
      f"⚽ **{display_name}**님이 피파 명단에 추가되었습니다! (현재"
      f" **{len(queue_fifa)}명**)"
  )


@bot.command(name="피파제거", aliases=["피파삭제"])
@commands.has_permissions(administrator=True)
async def remove_fifa_user(ctx, *, user_input: str = None):
  """관리자가 명단에서 유저를 삭제합니다."""
  if not user_input:
    await ctx.send("⚠️ 제거할 유저 이름을 입력해주세요! 예: `!피파제거 손흥민`")
    return

  display_name = user_input
  if ctx.message.mentions:
    display_name = ctx.message.mentions[0].display_name

  if display_name not in queue_fifa:
    await ctx.send(f"⚠️ **{display_name}**님은 현재 명단에 없습니다.")
    return

  queue_fifa.remove(display_name)
  await ctx.send(
      f"🚫 **{display_name}**님이 피파 명단에서 제거되었습니다. (남은 인원:"
      f" **{len(queue_fifa)}명**)"
  )


@bot.command(name="피파명단")
async def list_fifa(ctx):
  """현재 피파 명단을 확인합니다."""
  if not queue_fifa:
    await ctx.send("📋 현재 등록된 피파 참가자가 없습니다.")
    return

  msg = f"⚽ **[피파 내전 등록 명단 (총 {len(queue_fifa)}명)]**\n"
  for idx, name in enumerate(queue_fifa, start=1):
    msg += f"{idx}. {name}\n"

  await ctx.send(msg)


@bot.command(name="피파결과")
@commands.has_permissions(administrator=True)
async def add_fifa_match_result(
    ctx, p1_name: str, p1_score: int, p2_name: str, p2_score: int
):
  """경기 결과를 입력합니다. 승리한 유저는 다음 라운드 진출 명단에 자동 기록됩니다."""
  global fifa_winners

  p1_stat = get_or_init_fifa_stat(p1_name)
  p2_stat = get_or_init_fifa_stat(p2_name)

  p1_stat["gf"] += p1_score
  p1_stat["ga"] += p2_score
  p1_stat["gd"] = p1_stat["gf"] - p1_stat["ga"]

  p2_stat["gf"] += p2_score
  p2_stat["ga"] += p1_score
  p2_stat["gd"] = p2_stat["gf"] - p2_stat["ga"]

  if p1_score > p2_score:
    p1_stat["win"] += 1
    p1_stat["pts"] += 3
    p2_stat["loss"] += 1
    winner = p1_name
    result_text = f"🏆 **{p1_name}** 승리! (다음 라운드 진출 확정)"
  elif p2_score > p1_score:
    p2_stat["win"] += 1
    p2_stat["pts"] += 3
    p1_stat["loss"] += 1
    winner = p2_name
    result_text = f"🏆 **{p2_name}** 승리! (다음 라운드 진출 확정)"
  else:
    p1_stat["draw"] += 1
    p1_stat["pts"] += 1
    p2_stat["draw"] += 1
    p2_stat["pts"] += 1
    winner = None
    result_text = "🤝 **무승부!** (토너먼트에서는 승부차기 결과 포함 필요)"

  # 토너먼트 진행 중 승자가 존재하면 자동으로 다음 라운드 진출 명단에 추가
  if winner and winner not in fifa_winners:
    fifa_winners.append(winner)

  embed = discord.Embed(
      title="⚽ 경기 결과 등록 완료", description=result_text, color=0x3498DB
  )
  embed.add_field(
      name=f"{p1_name}",
      value=(
          f"스코어: **{p1_score}**점\n전적: {p1_stat['win']}승 {p1_stat['draw']}무"
          f" {p1_stat['loss']}패\n득실차: **{p1_stat['gd']:+d}**"
          f" ({p1_stat['gf']}득/{p1_stat['ga']}실)"
      ),
      inline=True,
  )
  embed.add_field(
      name=f"{p2_name}",
      value=(
          f"스코어: **{p2_score}**점\n전적: {p2_stat['win']}승 {p2_stat['draw']}무"
          f" {p2_stat['loss']}패\n득실차: **{p2_stat['gd']:+d}**"
          f" ({p2_stat['gf']}득/{p2_stat['ga']}실)"
      ),
      inline=True,
  )

  await ctx.send(embed=embed)


@bot.command(name="피파진출자", aliases=["피파승자"])
async def list_fifa_winners(ctx):
  """현재 승리하여 다음 라운드에 진출한 인원 목록을 확인합니다."""
  if not fifa_winners:
    await ctx.send("📋 아직 기록된 다음 라운드 진출자가 없습니다.")
    return

  msg = (
      f"🎟️ **[다음 라운드 진출 확정자 ({len(fifa_winners)}명)]**\n"
      + "\n".join([f"- {name}" for name in fifa_winners])
  )
  await ctx.send(msg)


@bot.command(name="피파토너먼트")
@commands.has_permissions(administrator=True)
async def make_fifa_tournament(ctx, rounds: int = None):
  """토너먼트 대진표를 새로 시작합니다. (2, 4, 8, 16)"""
  global last_fifa_group_embed, current_tournament_round, fifa_winners

  if rounds is None or rounds not in [2, 4, 8, 16, 32]:
    await ctx.send(
        "⚠️ 올바른 토너먼트 강수를 입력해주세요! (2, 4, 8, 16)\n예시:"
        " `!피파토너먼트 8`"
    )
    return

  current_count = len(queue_fifa)
  if current_count < 2:
    await ctx.send("❌ 토너먼트를 시작하려면 최소 2명의 참가자가 필요합니다!")
    return

  # 새로운 토너먼트 시작 시 승자 목록 리셋
  fifa_winners = []
  current_tournament_round = rounds

  shuffled = queue_fifa.copy()
  random.shuffle(shuffled)

  title_map = {2: "🏆 결승전 (2강)", 4: "4강전", 8: "8강전", 16: "16강전"}
  round_title = title_map.get(rounds, f"{rounds}강전")

  embed = discord.Embed(
      title=f"⚽ 피파온라인 {round_title} 토너먼트 대진표",
      description=f"총 참가자: **{current_count}명**",
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
  """승리자들만 모아 자동으로 다음 라운드 대진표를 생성합니다."""
  global last_fifa_group_embed, current_tournament_round, fifa_winners

  if not fifa_winners:
    await ctx.send(
        "❌ 다음 라운드로 진출한 승자가 없습니다! `!피파결과`로 경기를 먼저"
        " 진행해주세요."
    )
    return

  if len(fifa_winners) < 2:
    await ctx.send(
        f"🏆 **[최종 우승자]** 축하합니다! **{fifa_winners[0]}**님이 토너먼트 최종"
        " 우승을 차지했습니다!"
    )
    return

  next_round = current_tournament_round // 2
  current_tournament_round = next_round

  shuffled = fifa_winners.copy()
  fifa_winners = []  # 다음 라운드를 위해 승자 목록 리셋
  random.shuffle(shuffled)

  title_map = {2: "🏆 결승전 (2강)", 4: "4강전", 8: "8강전", 16: "16강전"}
  round_title = title_map.get(next_round, f"{next_round}강전")

  embed = discord.Embed(
      title=f"⚽ 피파온라인 {round_title} 대진표",
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
  """승점, 득실차, 다득점 순으로 정렬된 피파 리그 순위표를 출력합니다."""
  if not fifa_stats:
    await ctx.send("📊 기록된 피파 경기 전적이 없습니다.")
    return

  sorted_stats = sorted(
      fifa_stats.items(),
      key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]),
      reverse=True,
  )

  embed = discord.Embed(
      title="🏆 피파온라인 리그 순위표",
      description="정렬 기준: 승점 > 득실차 > 다득점",
      color=0xF1C40F,
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
  """최근 생성된 피파 조별/토너먼트 대진표를 다시 출력합니다."""
  if last_fifa_group_embed is None:
    await ctx.send("❌ 아직 생성된 피파 대진표가 없습니다!")
  else:
    await ctx.send(embed=last_fifa_group_embed)


@bot.command(name="피파초기화")
@commands.has_permissions(administrator=True)
async def reset_fifa(ctx):
  global queue_fifa, last_fifa_group_embed, fifa_stats, fifa_winners, current_tournament_round
  queue_fifa = []
  fifa_winners = []
  fifa_stats = {}
  current_tournament_round = 0
  last_fifa_group_embed = None
  await ctx.send("🔄 피파 명단, 전적/득실표 및 대진표가 모두 초기화되었습니다.")


# =========================================================
# --- [ 공통 관리자, 청소 및 차단 내역 명령어 ] ---
# =========================================================


@bot.command(name="청소", aliases=["삭제"])
@commands.has_permissions(administrator=True)
async def clear_messages(ctx, count: int = 10):
  """고정된 메시지를 스킵하고 지정한 개수만큼 일반 메시지를 삭제합니다."""
  if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
    await ctx.send("❌ 봇에게 이 채널의 **[메시지 관리]** 권한이 없습니다!")
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
      except discord.Forbidden:
        await ctx.send("❌ 메시지를 삭제할 권한이 부족합니다.")
        return
      except discord.HTTPException:
        pass
      except discord.NotFound:
        pass

    if deleted_count >= count:
      break

  notice = await ctx.send(
      f"🧹 고정 메시지를 제외하고 **{deleted_count}개**의 메시지를 정돈했습니다!"
  )
  await asyncio.sleep(3)
  try:
    await notice.delete()
  except Exception:
    pass


@bot.command(name="차단")
@commands.has_permissions(administrator=True)
async def ban_user(ctx, member: discord.Member, *, reason: str = None):
  if not reason:
    await ctx.send("⚠️ 차단 사유를 작성해주세요! 예: `!차단 @유저 사유`")
    return

  banned_users[member.id] = {"name": member.display_name, "reason": reason}

  if member in queue_5v5:
    queue_5v5.remove(member)
  if member in queue_1v1:
    queue_1v1.remove(member)

  await ctx.send(
      f"🚫 **{member.display_name}**님이 차단 목록에 등록되었습니다.\n사유: `{reason}`"
  )


@bot.command(name="차단해제")
@commands.has_permissions(administrator=True)
async def unban_user(ctx, member: discord.Member):
  if member.id in banned_users:
    del banned_users[member.id]
    await ctx.send(f"✅ **{member.display_name}**님의 차단이 해제되었습니다.")
  else:
    await ctx.send("해당 유저는 차단 목록에 없습니다.")


@bot.command(name="차단목록", aliases=["차단내역"])
async def list_banned_users(ctx):
  if not banned_users:
    await ctx.send("✅ 현재 차단된 유저가 없습니다.")
    return

  embed = discord.Embed(
      title="🚫 내전 차단 유저 목록",
      description=f"총 **{len(banned_users)}명**이 제재 중입니다.",
      color=0x8B0000,
  )

  for user_id, info in banned_users.items():
    embed.add_field(
        name=f"👤 {info['name']} (ID: {user_id})",
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
    await ctx.send(
        f"👋 **{member.display_name}**님을 명단에서 강제 제외했습니다."
    )
  else:
    await ctx.send("해당 유저는 현재 명단에 없습니다.")


# --- [ 권한 및 인자 예외 처리 ] ---
@bot.event
async def on_command_error(ctx, error):
  if isinstance(error, commands.MissingPermissions):
    await ctx.send("❌ 이 명령어는 **서버 관리자**만 사용할 수 있습니다.")
  elif isinstance(error, commands.MissingRequiredArgument):
    if ctx.command.name == "차단":
      await ctx.send("⚠️ 차단할 대상과 사유를 입력해주세요! 예: `!차단 @유저 사유`")


# --- [ 환경변수 토큰으로 봇 실행 ] ---
TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)