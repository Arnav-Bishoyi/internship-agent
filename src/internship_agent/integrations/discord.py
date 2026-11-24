import asyncio
import json
import threading
import discord
from discord import app_commands
from ..discovery.shared_roles import shared_url
from ..store import Store


def gateway(path,settings,token):
    client=discord.Client(intents=discord.Intents.none())
    tree=app_commands.CommandTree(client)
    guild=discord.Object(id=int(settings["guild"]))

    @tree.command(name="role",description="Save a LinkedIn or Handshake internship",guild=guild)
    async def role(interaction: discord.Interaction,url:str,details:str=""):
        if str(interaction.user.id)!=str(settings["user"]) or str(interaction.channel_id)!=str(settings["channel"]):
            await interaction.response.send_message("This channel or user is not configured for intake.",ephemeral=True)
            return
        try:
            link=shared_url(url)
        except ValueError as e:
            await interaction.response.send_message(str(e),ephemeral=True)
            return
        s=Store(path)
        try:
            created=s.lead(str(interaction.id),link,details[:6000],"Discord")
        finally:
            s.db.close()
        await interaction.response.send_message("Saved for matching." if created else "Already received.",ephemeral=True)

    @client.event
    async def setup_hook():
        await tree.sync(guild=guild)

    def run():
        client.run(token,log_handler=None)
    t=threading.Thread(target=run,daemon=True)
    t.start()
    return t
