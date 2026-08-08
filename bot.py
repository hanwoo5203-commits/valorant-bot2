import os
from threading import Thread
from flask import Flask

# --- Render 24시간 유지를 위한 Flask 웹서버 설정 ---
app = Flask("")


@app.route("/")
def home():
  return "Bot is alive!"


def run_web():
  # Render에서 지정해주는 포트(PORT)를 읽어서 실행합니다.
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


def keep_alive():
  t = Thread(target=run_web)
  t.start()


# 웹서버 실행
keep_alive()

# ----------------------------------------------------
import discord
from discord.ext import commands
import asyncio

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 데이터 저장 구조
queue = []          # 대기열 명단
is_open = False     # 선착순 오픈 여부 (기본값: 닫힘)
banned_users = set() # 차단(블랙리스트) 유저 ID 목록

@bot.event
async def on_ready():
    print(f'{bot.user.name} 봇이 준비되었습니다!')

# --- [일반 유저 명령어] ---

@bot.command()
async def 참가(ctx):
    user = ctx.author
    
    # 1. 오픈 여부 확인
    if not is_open:
        await ctx.send("❌ 아직 선착순 모집이 시작되지 않았습니다! 잠시만 기다려주세요.")
        return
        
    # 2. 제재(차단) 유저 확인
    if user.id in banned_users:
        await ctx.send(f"🚫 **{user.display_name}**님은 제재 처리되어 내전에 참가할 수 없습니다.")
        return

    # 3. 중복 참가 확인
    if user in queue:
        await ctx.send(f"⚠️ **{user.display_name}**님은 이미 신청하셨습니다.")
        return
    
    # 4. 정원 초과 확인 (10명 + 예비 1명 = 총 11명)
    if len(queue) >= 11:
        await ctx.send("❌ 대기열이 가득 차서 더 이상 신청할 수 없습니다. (최대 11명)")
        return

    queue.append(user)
    current_count = len(queue)
    
    if current_count <= 10:
        await ctx.send(f"✅ **{user.display_name}**님 참가 완료! ({current_count}/10명)")
    elif current_count == 11:
        await ctx.send(f"🎟️ **{user.display_name}**님 **[예비 1번]**으로 등록되었습니다!")

@bot.command()
async def 취소(ctx):
    user = ctx.author
    if user not in queue:
        await ctx.send(f"⚠️ **{user.display_name}**님은 명단에 없습니다.")
        return
        
    queue.remove(user)
    await ctx.send(f"🚫 **{user.display_name}**님의 참가가 취소되었습니다.")

@bot.command()
async def 명단(ctx):
    if not queue:
        await ctx.send("📋 현재 신청된 인원이 없습니다.")
        return
    
    status_str = "🟢 [모집 중]" if is_open else "🔴 [모집 종료/마감]"
    msg = f"📋 **[발로란트 내전 명단 - {status_str}]**\n"
    for idx, user in enumerate(queue):
        if idx < 10:
            msg += f"{idx + 1}. {user.display_name}\n"
        elif idx == 10:
            msg += f"-------------------\n예비 1번: {user.display_name}\n"
            
    await ctx.send(msg)


# --- [관리자 전용 명령어] ---

@bot.command()
@commands.has_permissions(administrator=True)
async def 오픈(ctx):
    global is_open
    is_open = True
    await ctx.send("🚨 **[선착순 모집 시작]** 지금부터 `!참가` 명령어를 사용할 수 있습니다!")

@bot.command()
@commands.has_permissions(administrator=True)
async def 예약(ctx, seconds: int):
    """지정한 초 뒤에 선착순을 오픈합니다 (예: !예약 60)"""
    global is_open
    await ctx.send(f"⏳ **{seconds}초 후**에 선착순 모집이 시작됩니다! 준비하세요!")
    await asyncio.sleep(seconds)
    is_open = True
    await ctx.send("🚨 **[선착순 모집 시작]** 지금부터 `!참가` 명령어를 입력하세요!")

@bot.command()
@commands.has_permissions(administrator=True)
async def 마감(ctx):
    global is_open
    is_open = False
    await ctx.send("🔒 선착순 모집이 닫혔습니다.")

@bot.command()
@commands.has_permissions(administrator=True)
async def 차단(ctx, member: discord.Member):
    """특정 유저의 내전 참가를 금지합니다 (예: !차단 @유저)"""
    banned_users.add(member.id)
    if member in queue:
        queue.remove(member)
    await ctx.send(f"🚫 **{member.display_name}**님을 내전 블랙리스트에 추가했습니다. (명단에서도 제거됨)")

@bot.command()
@commands.has_permissions(administrator=True)
async def 차단해제(ctx, member: discord.Member):
    """차단을 해제합니다 (예: !차단해제 @유저)"""
    if member.id in banned_users:
        banned_users.remove(member.id)
        await ctx.send(f"✅ **{member.display_name}**님의 차단이 해제되었습니다.")
    else:
        await ctx.send("해당 유저는 차단 목록에 없습니다.")

@bot.command()
@commands.has_permissions(administrator=True)
async def 강퇴(ctx, member: discord.Member):
    """명단에서 특정 유저를 지정하여 제외합니다 (예: !강퇴 @유저)"""
    if member in queue:
        queue.remove(member)
        await ctx.send(f"👋 **{member.display_name}**님을 명단에서 강제 제외했습니다.")
    else:
        await ctx.send("해당 유저는 현재 명단에 없습니다.")

@bot.command()
@commands.has_permissions(administrator=True)
async def 초기화(ctx):
    global queue, is_open
    queue = []
    is_open = False
    await ctx.send("🔄 대기열 및 모집 상태가 초기화되었습니다.")

import os

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)