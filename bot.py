import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import time
import random
import string
from datetime import datetime, timedelta

# ============================================================
# CONFIGURAÇÕES - edite aqui
# ============================================================
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "/"

# Cargo necessário para contratar (nome exato no servidor)
MANAGER_ROLE_ID = 1478981329491329138

# Cargo dado ao contratado após aceitar
MEMBER_ROLE = "Members"

# Canal onde os contratos são enviados (None = canal atual)
CONTRACT_CHANNEL_ID = 1478981421090734152

# Arquivo de banco de dados
DB_FILE = "contracts.json"

# Tempo para o contrato expirar (em horas)
CONTRACT_EXPIRY_HOURS = 24

# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
tree = bot.tree


# ============================================================
# BANCO DE DADOS (JSON simples)
# ============================================================

def load_db():
    if not os.path.exists(DB_FILE):
        return {"contracts": {}, "history": []}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def generate_contract_id(signee_id, contractor_id):
    ts = int(time.time() * 1000)
    return f"T{signee_id}_{contractor_id}{ts}"


# ============================================================
# VIEWS (Botões de Aceitar / Recusar)
# ============================================================

class ContractView(discord.ui.View):
    def __init__(self, contract_id: str, signee_id: int, contractor_id: int):
        super().__init__(timeout=None)  # timeout via task
        self.contract_id = contract_id
        self.signee_id = signee_id
        self.contractor_id = contractor_id

    @discord.ui.button(label="✅  Aceitar", style=discord.ButtonStyle.success, custom_id="accept_contract")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Só o contratado pode aceitar
        if interaction.user.id != self.signee_id:
            await interaction.response.send_message("❌ Apenas o contratado pode aceitar este contrato.", ephemeral=True)
            return

        db = load_db()
        contract = db["contracts"].get(self.contract_id)

        if not contract:
            await interaction.response.send_message("❌ Contrato não encontrado.", ephemeral=True)
            return

        if contract["status"] != "pending":
            await interaction.response.send_message("⚠️ Este contrato já foi processado.", ephemeral=True)
            return

        if time.time() > contract["expires_at"]:
            await interaction.response.send_message("⏰ Este contrato já expirou.", ephemeral=True)
            return

        # Atualiza status
        contract["status"] = "accepted"
        contract["answered_at"] = time.time()
        db["history"].append(contract)
        del db["contracts"][self.contract_id]
        save_db(db)

        # Dar cargo ao membro
        guild = interaction.guild
        member = guild.get_member(self.signee_id)
        role_id = contract.get("role_id")
        role = guild.get_role(role_id) if role_id else discord.utils.get(guild.roles, name=contract.get("role", MEMBER_ROLE))

        if member and role:
            await member.add_roles(role)

        # Atualiza embed
        embed = build_accepted_embed(contract)
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message(f"🎉 **{interaction.user.mention}** aceitou o contrato!", ephemeral=False)

    @discord.ui.button(label="❌  Recusar", style=discord.ButtonStyle.danger, custom_id="decline_contract")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.signee_id:
            await interaction.response.send_message("❌ Apenas o contratado pode recusar este contrato.", ephemeral=True)
            return

        db = load_db()
        contract = db["contracts"].get(self.contract_id)

        if not contract:
            await interaction.response.send_message("❌ Contrato não encontrado.", ephemeral=True)
            return

        if contract["status"] != "pending":
            await interaction.response.send_message("⚠️ Este contrato já foi processado.", ephemeral=True)
            return

        contract["status"] = "declined"
        contract["answered_at"] = time.time()
        db["history"].append(contract)
        del db["contracts"][self.contract_id]
        save_db(db)

        embed = build_declined_embed(contract)
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message(f"❌ **{interaction.user.mention}** recusou o contrato.", ephemeral=False)


# ============================================================
# EMBEDS
# ============================================================

def build_contract_embed(contract: dict) -> discord.Embed:
    embed = discord.Embed(
        color=0xF5A623,
        description=""
    )
    embed.set_author(name="📋  Proposta de Contrato — BRF League", icon_url="https://cdn.discordapp.com/attachments/1453138965854158952/1483997859450716221/file_000000003994720e91b4741aabcc2e4c.png?ex=69bca035&is=69bb4eb5&hm=e8dd2da14c164cf6941641db48b831f59caf29203a4196d224a8862af33f5b2f&")

    embed.add_field(name="Signee", value=f"<@{contract['signee_id']}>\n`{contract['signee_name']}`", inline=True)
    embed.add_field(name="Contractor", value=f"<@{contract['contractor_id']}>\n`{contract['contractor_name']}`", inline=True)
    embed.add_field(name="Contract ID", value=f"`{contract['contract_id']}`", inline=True)

    embed.add_field(name="Team", value=contract.get("team", "—"), inline=True)
    embed.add_field(name="Position", value=contract.get("position", "—"), inline=True)
    embed.add_field(name="Role", value=contract.get("role", MEMBER_ROLE), inline=True)

    issued = datetime.fromtimestamp(contract["created_at"]).strftime("%d/%m/%Y, %H:%M")
    expires = datetime.fromtimestamp(contract["expires_at"]).strftime("%d/%m/%Y, %H:%M")
    embed.set_footer(text=f"BRF League  •  {issued}  →  {expires}")

    return embed

def build_expired_embed(contract: dict) -> discord.Embed:
    embed = discord.Embed(
        color=0x992D22,
        title="⏰  Contract Expired",
        description="This contract has expired. Ask the manager to send a new offer if you're still interested."
    )
    embed.add_field(name="Signee", value=f"<@{contract['signee_id']}>\n`{contract['signee_name']}`", inline=True)
    embed.add_field(name="Contractor", value=f"<@{contract['contractor_id']}>\n`{contract['contractor_name']}`", inline=True)
    embed.add_field(name="Contract ID", value=f"`{contract['contract_id']}`", inline=True)

    embed.add_field(name="Team", value=contract.get("team", "—"), inline=True)
    embed.add_field(name="Position", value=contract.get("position", "—"), inline=True)
    embed.add_field(name="Role", value=contract.get("role", MEMBER_ROLE), inline=True)

    issued = datetime.fromtimestamp(contract["created_at"]).strftime("%d/%m/%Y, %H:%M")
    expires = datetime.fromtimestamp(contract["expires_at"]).strftime("%d/%m/%Y, %H:%M")
    embed.set_footer(text=f"BRF League  •  {issued}  →  {expires}")
    return embed

def build_accepted_embed(contract: dict) -> discord.Embed:
    embed = discord.Embed(
        color=0x2ECC71,
        title="✅  Contract Accepted",
        description=f"<@{contract['signee_id']}> aceitou o contrato e agora faz parte do time **{contract.get('team','—')}**!"
    )
    embed.add_field(name="Signee", value=f"<@{contract['signee_id']}>\n`{contract['signee_name']}`", inline=True)
    embed.add_field(name="Contractor", value=f"<@{contract['contractor_id']}>\n`{contract['contractor_name']}`", inline=True)
    embed.add_field(name="Contract ID", value=f"`{contract['contract_id']}`", inline=True)
    embed.set_footer(text="BRF League")
    return embed

def build_declined_embed(contract: dict) -> discord.Embed:
    embed = discord.Embed(
        color=0x95A5A6,
        title="❌  Contract Declined",
        description=f"<@{contract['signee_id']}> recusou a proposta de contrato."
    )
    embed.add_field(name="Signee", value=f"<@{contract['signee_id']}>\n`{contract['signee_name']}`", inline=True)
    embed.add_field(name="Contractor", value=f"<@{contract['contractor_id']}>\n`{contract['contractor_name']}`", inline=True)
    embed.add_field(name="Contract ID", value=f"`{contract['contract_id']}`", inline=True)
    embed.set_footer(text="BRF League")
    return embed


# ============================================================
# SLASH COMMANDS
# ============================================================

@tree.command(name="contratar", description="Envia uma proposta de contrato para um membro")
@app_commands.describe(
    membro="O usuário que você quer contratar",
    nome_time="Nome do time",
    posicao="Posição (ex: st/mc, goleiro...)",
    cargo="Marque o @ do cargo que será dado ao contratado"
)
async def contratar(
    interaction: discord.Interaction,
    membro: discord.Member,
    nome_time: str,
    posicao: str,
    cargo: discord.Role
):
    # Verificar se tem permissão
    manager_role = interaction.guild.get_role(MANAGER_ROLE_ID)
    if manager_role not in interaction.user.roles:
        await interaction.response.send_message(
            f"❌ Você precisa ter o cargo de Manager para contratar membros.",
            ephemeral=True
        )
        return

    if membro.bot:
        await interaction.response.send_message("❌ Você não pode contratar um bot.", ephemeral=True)
        return

    if membro.id == interaction.user.id:
        await interaction.response.send_message("❌ Você não pode contratar a si mesmo.", ephemeral=True)
        return

    # Criar contrato
    contract_id = generate_contract_id(membro.id, interaction.user.id)
    now = time.time()
    expires_at = now + (CONTRACT_EXPIRY_HOURS * 3600)

    contract = {
        "contract_id": contract_id,
        "signee_id": membro.id,
        "signee_name": membro.name,
        "contractor_id": interaction.user.id,
        "contractor_name": interaction.user.name,
        "team": nome_time,
        "position": posicao,
        "role": cargo.name,
        "role_id": cargo.id,
        "status": "pending",
        "created_at": now,
        "expires_at": expires_at,
        "message_id": None,
        "channel_id": CONTRACT_CHANNEL_ID
    }

    db = load_db()
    db["contracts"][contract_id] = contract
    save_db(db)

    embed = build_contract_embed(contract)
    view = ContractView(contract_id, membro.id, interaction.user.id)

    # Enviar sempre no canal de contratos
    contract_channel = interaction.guild.get_channel(CONTRACT_CHANNEL_ID)
    if contract_channel is None:
        await interaction.response.send_message("❌ Canal de contratos não encontrado. Verifique o CONTRACT_CHANNEL_ID.", ephemeral=True)
        return

    # Responde ephemeral para não poluir o canal atual
    if interaction.channel_id != CONTRACT_CHANNEL_ID:
        await interaction.response.send_message("✅ Contrato enviado!", ephemeral=True)
        msg = await contract_channel.send(
            content=f"{membro.mention}, Contract `{contract_id}` has been proposed by {interaction.user.mention}.",
            embed=embed,
            view=view
        )
    else:
        await interaction.response.send_message(
            content=f"{membro.mention}, Contract `{contract_id}` has been proposed by {interaction.user.mention}.",
            embed=embed,
            view=view
        )
        msg = await interaction.original_response()

    # Salvar message_id
    db = load_db()
    if contract_id in db["contracts"]:
        db["contracts"][contract_id]["message_id"] = msg.id
        save_db(db)


@tree.command(name="historico", description="Veja o histórico de contratos do servidor")
@app_commands.describe(membro="Filtrar por membro (opcional)")
async def historico(interaction: discord.Interaction, membro: discord.Member = None):
    db = load_db()
    history = db.get("history", [])

    if membro:
        history = [c for c in history if c["signee_id"] == membro.id or c["contractor_id"] == membro.id]

    if not history:
        await interaction.response.send_message("📭 Nenhum contrato encontrado.", ephemeral=True)
        return

    history = history[-10:]  # Últimos 10

    embed = discord.Embed(title="📋 Histórico de Contratos — BRF", color=0x3498DB)
    for c in reversed(history):
        status_emoji = {"accepted": "✅", "declined": "❌", "expired": "⏰"}.get(c["status"], "❓")
        embed.add_field(
            name=f"{status_emoji} `{c['contract_id'][:30]}...`",
            value=f"**{c.get('team','—')}** | <@{c['signee_id']}> ← <@{c['contractor_id']}>\n`{c['position']}` • {c['status'].upper()}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="contratos_ativos", description="Veja contratos pendentes")
async def contratos_ativos(interaction: discord.Interaction):
    manager_role = interaction.guild.get_role(MANAGER_ROLE_ID)
    if manager_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return

    db = load_db()
    pending = [c for c in db["contracts"].values() if c["status"] == "pending"]

    if not pending:
        await interaction.response.send_message("✅ Nenhum contrato pendente.", ephemeral=True)
        return

    embed = discord.Embed(title="⏳ Contratos Pendentes — BRF", color=0xF5A623)
    for c in pending:
        expires = datetime.fromtimestamp(c["expires_at"]).strftime("%d/%m %H:%M")
        embed.add_field(
            name=f"🔸 {c.get('team','—')} — {c['position']}",
            value=f"<@{c['signee_id']}> ← <@{c['contractor_id']}>\nExpira: `{expires}`",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="cancelar_contrato", description="Cancela um contrato pendente pelo ID")
@app_commands.describe(contract_id="ID do contrato a cancelar")
async def cancelar_contrato(interaction: discord.Interaction, contract_id: str):
    db = load_db()
    contract = db["contracts"].get(contract_id)

    if not contract:
        await interaction.response.send_message("❌ Contrato não encontrado.", ephemeral=True)
        return

    is_contractor = interaction.user.id == contract["contractor_id"]
    manager_role = interaction.guild.get_role(MANAGER_ROLE_ID)
    is_manager = manager_role in interaction.user.roles

    if not is_contractor and not is_manager:
        await interaction.response.send_message("❌ Apenas quem enviou o contrato pode cancelá-lo.", ephemeral=True)
        return

    contract["status"] = "cancelled"
    db["history"].append(contract)
    del db["contracts"][contract_id]
    save_db(db)

    await interaction.response.send_message(f"🗑️ Contrato `{contract_id}` cancelado com sucesso.", ephemeral=True)


# ============================================================
# TASK: verificar contratos expirados
# ============================================================

@tasks.loop(minutes=5)
async def check_expired_contracts():
    db = load_db()
    now = time.time()
    expired_ids = []

    for cid, contract in db["contracts"].items():
        if contract["status"] == "pending" and now > contract["expires_at"]:
            expired_ids.append(cid)

    for cid in expired_ids:
        contract = db["contracts"][cid]
        contract["status"] = "expired"
        db["history"].append(contract)

        # Editar mensagem no Discord
        try:
            channel = bot.get_channel(contract["channel_id"])
            if channel and contract.get("message_id"):
                msg = await channel.fetch_message(contract["message_id"])
                embed = build_expired_embed(contract)
                await msg.edit(embed=embed, view=None)
        except Exception as e:
            print(f"[WARN] Não foi possível editar mensagem do contrato {cid}: {e}")

        del db["contracts"][cid]

    if expired_ids:
        save_db(db)
        print(f"[INFO] {len(expired_ids)} contrato(s) expirado(s).")


# ============================================================
# EVENTOS
# ============================================================

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user} ({bot.user.id})")
    await tree.sync()
    check_expired_contracts.start()
    print("✅ Slash commands sincronizados!")


# ============================================================
# INICIAR
# ============================================================

bot.run(TOKEN)