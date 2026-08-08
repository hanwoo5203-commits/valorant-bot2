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
# 5v5 내전 데이터 (주전 10명 + 예비 5명 = 총 15명)
queue_5v5 = []
is_open_5v5 = False
reserved_time_5v5 = None  # 예약 시간 HH:MM
reserved_channel_5v5 = None  # 예약을 실행한 채널

# 1v1 내전 데이터 (개인 참가 대기열)
queue_1v1 = []
is_open_1v1 = False
last_bracket_embed = None  # 생성된 대진표 임베드 저장용 변수

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


# --- [ 백그라운드 예약 시각 체크 루프 ] ---
@tasks.loop(seconds=30)
async def check_reservation_loop():
  global is_open_5v5, reserved_time_5v5, reserved_channel_5v5
  if reserved_time_5v5 is None:
    return

  # 한국 표준시(KST = UTC+9) 계산
  now_kst = datetime.datetime.now(
      datetime.timezone(datetime.timedelta(hours=9))
  )
  current_time_str = now_kst.strftime("%H:%M")

  if current_time_str == reserved_time_5v5:
    is_open_5v5 = True
    target_channel = reserved_channel_5v5

    # 예약 변수 초기화
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
  """사용법: !예약시간 15:00 (원하는 24시간제 시각 지정)"""
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
  """짧은 대기시간(초 단위) 예약용 명령어"""
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
  """본인 또는 지정 유저의 1v1 전적 및 티어 조회"""
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
  """1v1 승수 TOP 5 순위표"""
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
  """가장 최근에 생성된 1v1 대진표를 다시 출력합니다."""
  if last_bracket_embed is None:
    await ctx.send(
        "❌ 아직 생성된 대진표가 없습니다! 관리자에게 `!1v1대진표`를 요청하세요."
    )
  else:
    await ctx.send(embed=last_bracket_embed)


# --- [ 관리자 전용 1v1 대진표 생성 및 제어 명령어 ] ---


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
  """참가자들을 무작위 셔플하여 1v1 대진표를 생성합니다."""
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

  # 대진표 저장
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
  """관리자가 특정 유저에게 1v1 승리 1회를 추가합니다"""
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
  """관리자가 특정 유저의 1v1 승리 1회를 차감합니다"""
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
  """관리자가 특정 유저의 1v1 승수를 직접 설정합니다"""
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
  """모든 유저의 1v1 전적 데이터를 초기화합니다"""
  global user_wins_1v1
  user_wins_1v1 = {}
  await ctx.send("🧹 모든 유저의 1v1 전적 및 티어 정보가 초기화되었습니다.")


# =========================================================
# --- [ 공통 관리자, 청소 및 차단 내역 명령어 ] ---
# =========================================================


@bot.command(name="청소", aliases=["삭제"])
@commands.has_permissions(administrator=True)
async def clear_messages(ctx, count: int = 10):
  """고정된 메시지를 스킵하고 지정한 개수만큼 일반 메시지를 삭제합니다.

  사용법: !청소 20
  """
  await ctx.message.delete()

  deleted_count = 0
  pinned_messages = await ctx.channel.pins()
  pinned_ids = [m.id for m in pinned_messages]

  # 최근 메시지를 스캔하며 고정 안 된 메시지만 삭제
  async for message in ctx.channel.history(limit=count * 2):
    if message.id not in pinned_ids:
      try:
        await message.delete()
        deleted_count += 1
        await asyncio.sleep(0.3)
      except discord.NotFound:
        pass

    if deleted_count >= count:
      break

  notice = await ctx.send(
      f"🧹 고정 메시지를 제외하고 **{deleted_count}개**의 메시지를 정돈했습니다!"
  )
  await asyncio.sleep(3)
  await notice.delete()


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
  """누구나 차단된 유저 목록과 사유를 확인할 수 있습니다."""
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
        f"👋 **{member.display_name}**님을 모든 명단에서 강제 제외했습니다."
    )
  else:
    await ctx.send("해당 유저는 현재 어떤 명단에도 없습니다.")


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