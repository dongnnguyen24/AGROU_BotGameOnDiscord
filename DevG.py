import discord
from discord.ext import commands, tasks
import asyncio
from collections import defaultdict, Counter
import random

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# --- BIẾN TOÀN CỤC GAME ---
alive_players = []
dead_players = []
player_roles = {}  # discord.Member -> role
EMOJIS = ['😀', '😎', '🧐', '😈', '🤠', '👻', '🧙', '👽', '🤖', '🧛']

vote_message = None
vote_map = {}  # user_id: emoji (vote)
revote_in_progress = False

roles_available = ["Sói", "Dân làng", "Tiên tri", "Bảo vệ", "Phù thủy", "Thợ săn"]
role_targets = {}  # dùng cho hành động đêm

def reset_game():
    global alive_players, dead_players, player_roles, vote_message, vote_map, revote_in_progress, role_targets
    alive_players = []
    dead_players = []
    player_roles = {}
    vote_message = None
    vote_map = {}
    revote_in_progress = False
    role_targets = {}

async def ask_night_action(player, role):
    try:
        if role == "Sói":
            await player.send("🌙 Bạn là Sói, hãy trả lời bằng tên hiển thị người bạn muốn giết đêm nay:")
        elif role == "Bảo vệ":
            await player.send("🌙 Bạn là Bảo vệ, hãy trả lời tên người bạn muốn bảo vệ đêm nay (hoặc 'none' để không bảo vệ ai):")
        elif role == "Phù thủy":
            await player.send("🌙 Bạn là Phù thủy, hãy trả lời tên người bạn muốn cứu hoặc giết đêm nay, định dạng 'cứu [tên]' hoặc 'giết [tên]' (hoặc 'none'):")
        elif role == "Tiên tri":
            await player.send("🌙 Bạn là Tiên tri, hãy trả lời tên người bạn muốn soi vai trò đêm nay:")

        def check(m):
            return m.author == player and isinstance(m.channel, discord.DMChannel)

        msg = await bot.wait_for('message', timeout=60.0, check=check)
        return msg.content.strip()
    except asyncio.TimeoutError:
        try:
            await player.send("⏰ Bạn đã hết thời gian trả lời, sẽ không có hành động đêm cho bạn.")
        except:
            pass
        return None
    except discord.Forbidden:
        await player.send("⚠️ Bot không thể gửi tin nhắn riêng cho bạn, vui lòng bật tin nhắn riêng tư.")
        return None

# --- LỆNH RESET ---
@bot.command()
async def reset(ctx):
    reset_game()
    await ctx.send("🔄 Trò chơi đã được reset. Dùng !start để bắt đầu lại.")

# --- LỆNH START ---
@bot.command()
async def start(ctx):
    reset_game()
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("❗ Bạn phải vào voice channel để bắt đầu game.")
        return

    channel = ctx.author.voice.channel
    members = [m for m in channel.members if not m.bot]
    if len(members) < 3:
        await ctx.send("❗ Cần ít nhất 3 người để chơi game.")
        return

    random.shuffle(members)
    alive_players.extend(members)
    assigned_roles = random.choices(roles_available, k=len(members))

    for member, role in zip(members, assigned_roles):
        player_roles[member] = role
        try:
            await member.send(f"🎭 Vai trò của bạn là: **{role}**")
        except:
            await ctx.send(f"⚠️ Không thể gửi vai trò cho {member.display_name}. Hãy bật tin nhắn riêng từ server.")

    await ctx.send("✅ Trò chơi đã bắt đầu! Vai trò đã được gửi qua DM.")

# --- LỆNH XEM LẠI VAI TRÒ ---
@bot.command()
async def role(ctx):
    if ctx.author not in player_roles:
        await ctx.send("❗ Bạn không phải là người chơi trong game.")
        return
    try:
        await ctx.author.send(f"🎭 Vai trò của bạn là: **{player_roles[ctx.author]}**")
    except:
        await ctx.send("⚠️ Không thể gửi vai trò. Hãy bật tin nhắn riêng từ server.")

# --- LỆNH BỎ PHIẾU NGÀY ---
@bot.command()
async def ngay(ctx):
    global vote_message, vote_map, revote_in_progress

    if not alive_players:
        await ctx.send("❗ Chưa có game hoặc không có người chơi còn sống.")
        return

    if revote_in_progress:
        await ctx.send("⏳ Đang diễn ra vòng vote lại, vui lòng chờ.")
        return

    voters = alive_players.copy()
    vote_map.clear()

    emojis_for_vote = EMOJIS[:len(voters)]
    vote_options_text = "\n".join(f"{e} - {p.display_name}" for e, p in zip(emojis_for_vote, voters))

    embed = discord.Embed(title="🌞 Bỏ phiếu ban ngày", description=f"Hãy vote bằng cách nhấn emoji trong 60 giây.\n\n{vote_options_text}", color=0xffcc00)
    vote_message = await ctx.send(embed=embed)

    for e in emojis_for_vote:
        await vote_message.add_reaction(e)

    def check(reaction, user):
        return reaction.message.id == vote_message.id and user in voters and str(reaction.emoji) in emojis_for_vote

    try:
        while True:
            reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
            if user.id in vote_map:
                for r in vote_message.reactions:
                    if str(r.emoji) == vote_map[user.id]:
                        users = await r.users().flatten()
                        if user in users:
                            await vote_message.remove_reaction(r.emoji, user)
                vote_map[user.id] = str(reaction.emoji)
            else:
                vote_map[user.id] = str(reaction.emoji)
    except asyncio.TimeoutError:
        await xu_ly_bopheu(ctx)

# --- XỬ LÝ PHIẾU ---
async def xu_ly_bopheu(ctx):
    global revote_in_progress, vote_map, vote_message

    counts = Counter(vote_map.values())

    if not counts:
        await ctx.send("❌ Không có ai bỏ phiếu, không loại ai.")
        return

    max_votes = max(counts.values())
    top_candidates = [e for e, c in counts.items() if c == max_votes]

    if len(top_candidates) > 1:
        revote_in_progress = True
        await ctx.send(f"⚠️ Hòa phiếu giữa các lựa chọn {top_candidates}, thêm 60 giây để vote lại!")

        await vote_message.clear_reactions()
        vote_map.clear()

        emojis_for_revote = top_candidates
        vote_options_text = "\n".join(f"{e}" for e in emojis_for_revote)
        embed = discord.Embed(title="🔄 Bỏ phiếu lại (revote)", description=f"Hãy vote lại bằng emoji trong 60 giây.\n\n{vote_options_text}", color=0xffcc00)
        await vote_message.edit(embed=embed)

        for e in emojis_for_revote:
            await vote_message.add_reaction(e)

        def check_revote(reaction, user):
            return reaction.message.id == vote_message.id and user in alive_players and str(reaction.emoji) in emojis_for_revote

        try:
            while True:
                reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check_revote)
                if user.id in vote_map:
                    for r in vote_message.reactions:
                        if str(r.emoji) == vote_map[user.id]:
                            users = await r.users().flatten()
                            if user in users:
                                await vote_message.remove_reaction(r.emoji, user)
                    vote_map[user.id] = str(reaction.emoji)
                else:
                    vote_map[user.id] = str(reaction.emoji)
        except asyncio.TimeoutError:
            revote_in_progress = False
            await xu_ly_bopheu_ketqua(ctx)
    else:
        await xu_ly_bopheu_ketqua(ctx)

# --- KẾT QUẢ SAU VOTE ---
async def xu_ly_bopheu_ketqua(ctx):
    global vote_map, vote_message

    counts = Counter(vote_map.values())
    if not counts:
        await ctx.send("❌ Không có ai bỏ phiếu, không loại ai.")
        return

    max_votes = max(counts.values())
    emoji = [e for e, c in counts.items() if c == max_votes][0]

    idx = EMOJIS.index(emoji)
    if idx >= len(alive_players):
        await ctx.send("❌ Lỗi không tìm thấy người bị loại.")
        return
    player_out = alive_players[idx]

    alive_players.remove(player_out)
    dead_players.append((player_out, player_roles[player_out]))

    await ctx.send(f"☠️ {player_out.display_name} bị treo cổ và bị loại khỏi trò chơi! (Vai trò ẩn)")

    if vote_message:
        await vote_message.delete()
        vote_message = None

    win_message = check_win()
    if win_message:
        await ctx.send(f"🏁 Trò chơi kết thúc! {win_message}")
        await hien_thi_thong_ke(ctx)
    else:
        await ctx.send("🎮 Trò chơi tiếp tục, chuyển sang đêm hoặc lượt tiếp theo.")

# --- LỆNH ĐÊM ---
@bot.command()
async def dem(ctx):
    global night_actions

    if not alive_players:
        await ctx.send("❗ Chưa có game hoặc không có người chơi còn sống.")
        return

    await ctx.send("🌙 Đêm bắt đầu! Các vai trò đặc biệt sẽ nhận tin nhắn riêng để thực hiện hành động.")

    night_actions = {
        "Sói": None,
        "Bảo vệ": None,
        "Phù thủy": None,
        "Tiên tri": None,
    }

    # Lấy danh sách người chơi từng vai
    roles_players = {
        role: [p for p in alive_players if player_roles.get(p) == role]
        for role in ["Sói", "Bảo vệ", "Phù thủy", "Tiên tri"]
    }

    # 1. Sói chọn mục tiêu (nếu nhiều sói thì có thể làm logic riêng, đơn giản lấy người sói đầu tiên)
    if roles_players["Sói"]:
        killer = roles_players["Sói"][0]
        response = await ask_night_action(killer, "Sói")
        if response:
            night_actions["Sói"] = response

    # 2. Bảo vệ chọn người bảo vệ
    if roles_players["Bảo vệ"]:
        protector = roles_players["Bảo vệ"][0]
        response = await ask_night_action(protector, "Bảo vệ")
        if response:
            night_actions["Bảo vệ"] = response

    # 3. Phù thủy chọn cứu hoặc giết
    if roles_players["Phù thủy"]:
        witch = roles_players["Phù thủy"][0]
        response = await ask_night_action(witch, "Phù thủy")
        if response:
            night_actions["Phù thủy"] = response

    # 4. Tiên tri soi vai trò
    if roles_players["Tiên tri"]:
        prophet = roles_players["Tiên tri"][0]
        response = await ask_night_action(prophet, "Tiên tri")
        if response:
            # Soi vai trò và trả lời qua DM
            found = None
            for p in alive_players:
                if p.display_name.lower() == response.lower():
                    found = p
                    break
            if found:
                role_of_found = player_roles.get(found, "Không xác định")
                await prophet.send(f"🔮 Vai trò của **{found.display_name}** là: **{role_of_found}**")
            else:
                await prophet.send("❌ Không tìm thấy người chơi với tên đó.")

    # Xử lý kết quả đêm
    victim_name = night_actions["Sói"]
    protected_name = night_actions["Bảo vệ"]
    witch_action = night_actions["Phù thủy"]

    victim_player = None
    for p in alive_players:
        if p.display_name.lower() == (victim_name or "").lower():
            victim_player = p
            break

    protected_player = None
    for p in alive_players:
        if p.display_name.lower() == (protected_name or "").lower():
            protected_player = p
            break

    # Phù thủy hành động
    witch_save = None
    witch_kill = None
    if witch_action and witch_action.lower() != "none":
        parts = witch_action.split()
        if len(parts) == 2:
            act, target_name = parts[0].lower(), parts[1]
            target_player = None
            for p in alive_players:
                if p.display_name.lower() == target_name.lower():
                    target_player = p
                    break
            if target_player:
                if act == "cứu" or act == "cuu":
                    witch_save = target_player
                elif act == "giết" or act == "giet":
                    witch_kill = target_player

    # Xử lý kết quả giết người
    killed_player = None
    if victim_player and victim_player != protected_player:
        killed_player = victim_player

    if witch_kill and witch_kill != protected_player:
        killed_player = witch_kill

    if witch_save and witch_save == victim_player:
        killed_player = None

    if killed_player:
        alive_players.remove(killed_player)
        dead_players.append((killed_player, player_roles.get(killed_player, "Không xác định")))
        await ctx.send(f"☠️ {killed_player.display_name} đã bị giết trong đêm qua! (Vai trò ẩn)")
    else:
        await ctx.send("🌙 Đêm qua không có ai chết.")

    win_message = check_win()
    if win_message:
        await ctx.send(f"🏁 Trò chơi kết thúc! {win_message}")
        await hien_thi_thong_ke(ctx)
    else:
        await ctx.send("🎮 Trò chơi tiếp tục, bắt đầu ngày mới với lệnh !ngay.")


# --- LỆNH STATUS ---
@bot.command()
async def status(ctx):
    if not player_roles:
        await ctx.send("❌ Chưa có game nào được bắt đầu.")
        return

    msg = "**📊 Trạng thái hiện tại:**\n\n"
    msg += "🟢 **Người còn sống:**\n"
    for p in alive_players:
        msg += f"- {p.display_name}\n"

    msg += "\n🔴 **Người đã chết:**\n"
    for p, role in dead_players:
        msg += f"- {p.display_name} ({role})\n"

    await ctx.send(msg)


# --- THỐNG KÊ SAU GAME ---
async def hien_thi_thong_ke(ctx):
    msg = "📋 **Vai trò người chơi:**\n"
    for p in player_roles:
        status = "✅ sống" if p in alive_players else "☠️ chết"
        msg += f"- {p.display_name}: {player_roles[p]} ({status})\n"

    msg += "\n📊 **Thống kê hành động:**\n- (Đang cập nhật...)"
    await ctx.send(msg)

# --- HÀM KIỂM TRA WIN ---
def check_win():
    if len(alive_players) == 1:
        return f"{alive_players[0].display_name} là người chiến thắng!"
    return None

# --- KHỞI ĐỘNG BOT ---
bot.run("MTM3NTgxOTcyMzc1NzA2MDE4OA.GIEDsj.wn-h23cTX67v6LN0SjlTYrw7Dxd67AmCb0_mvE")