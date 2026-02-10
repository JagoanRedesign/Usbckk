import asyncio
import logging
import json
import time
import random
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Pyrogram untuk UserBot (MTProto)
from pyrogram import Client, filters, idle
from pyrogram.types import Message, Chat, User
from pyrogram.errors import FloodWait, RPCError

# python-telegram-bot untuk Bot Kontrol (Bot API)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters as tg_filters
)

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================ DATABASE SETUP ============================

class Database:
    def __init__(self, db_path: str = "userbot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    api_id INTEGER,
                    api_hash TEXT,
                    session_string TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Campaigns table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    name TEXT,
                    message_text TEXT,
                    media_path TEXT,
                    schedule_type TEXT,
                    interval_minutes INTEGER,
                    specific_times TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Groups table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS target_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER,
                    chat_id INTEGER,
                    chat_title TEXT,
                    thread_id INTEGER,
                    delay_seconds INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                )
            ''')
            
            # Statistics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER,
                    chat_id INTEGER,
                    sent_at TIMESTAMP,
                    status TEXT,
                    error_message TEXT,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
                )
            ''')
            
            # Settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    user_id INTEGER PRIMARY KEY,
                    admin_controls TEXT,
                    notification_chat_id INTEGER,
                    max_messages_per_day INTEGER DEFAULT 100,
                    delay_between_messages INTEGER DEFAULT 30,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Trial users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trial_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            conn.commit()
    
    def add_user(self, user_id: int, api_id: int, api_hash: str, session_string: str):
        """Add or update user"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, api_id, api_hash, session_string, is_active)
                VALUES (?, ?, ?, ?, 1)
            ''', (user_id, api_id, api_hash, session_string))
            conn.commit()
    
    def get_user_sessions(self) -> List[Tuple]:
        """Get all active user sessions"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, api_id, api_hash, session_string 
                FROM users 
                WHERE is_active = 1
            ''')
            return cursor.fetchall()

# ============================ USERBOT MANAGER ============================

class UserBotManager:
    def __init__(self):
        self.db = Database()
        self.userbots: Dict[int, Client] = {}
        self.active_campaigns: Dict[int, asyncio.Task] = {}
        self.is_running = True
    
    async def initialize_all_userbots(self):
        """Initialize all userbots from database"""
        sessions = self.db.get_user_sessions()
        for user_id, api_id, api_hash, session_string in sessions:
            try:
                await self.create_userbot(user_id, api_id, api_hash, session_string)
                logger.info(f"UserBot initialized for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to initialize UserBot for user {user_id}: {e}")
    
    async def create_userbot(self, user_id: int, api_id: int, api_hash: str, session_string: str):
        """Create and start a userbot session"""
        app = Client(
            f"userbot_{user_id}",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            in_memory=True
        )
        
        @app.on_message(filters.command("start", prefixes="/") & filters.private)
        async def start_command(client, message: Message):
            await message.reply("🤖 UserBot aktif dan siap untuk promosi otomatis!")
        
        # Start the userbot
        await app.start()
        self.userbots[user_id] = app
        return app
    
    async def send_promotion_message(self, user_id: int, chat_id: int, 
                                     message_text: str, media_path: Optional[str] = None,
                                     thread_id: Optional[int] = None, delay: int = 0):
        """Send promotion message to a specific chat"""
        if user_id not in self.userbots:
            return False, "UserBot tidak aktif"
        
        if delay > 0:
            await asyncio.sleep(delay)
        
        try:
            app = self.userbots[user_id]
            
            if media_path and Path(media_path).exists():
                if media_path.endswith(('.jpg', '.jpeg', '.png')):
                    await app.send_photo(
                        chat_id=chat_id,
                        photo=media_path,
                        caption=message_text,
                        message_thread_id=thread_id
                    )
                elif media_path.endswith(('.mp4', '.mov', '.avi')):
                    await app.send_video(
                        chat_id=chat_id,
                        video=media_path,
                        caption=message_text,
                        message_thread_id=thread_id
                    )
                elif media_path.endswith('.gif'):
                    await app.send_animation(
                        chat_id=chat_id,
                        animation=media_path,
                        caption=message_text,
                        message_thread_id=thread_id
                    )
                else:
                    await app.send_document(
                        chat_id=chat_id,
                        document=media_path,
                        caption=message_text,
                        message_thread_id=thread_id
                    )
            else:
                await app.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    message_thread_id=thread_id
                )
            
            return True, "Pesan berhasil dikirim"
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return await self.send_promotion_message(user_id, chat_id, message_text, media_path, thread_id, 0)
        except Exception as e:
            return False, str(e)
    
    async def run_campaign(self, campaign_id: int):
        """Run a specific campaign continuously"""
        while self.is_running:
            try:
                # Get campaign details from database
                with sqlite3.connect(self.db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT c.user_id, c.message_text, c.media_path, 
                               c.interval_minutes, tg.chat_id, tg.thread_id, tg.delay_seconds
                        FROM campaigns c
                        JOIN target_groups tg ON c.id = tg.campaign_id
                        WHERE c.id = ? AND c.is_active = 1 AND tg.is_active = 1
                    ''', (campaign_id,))
                    targets = cursor.fetchall()
                
                if not targets:
                    await asyncio.sleep(60)
                    continue
                
                user_id, message_text, media_path, interval, _, _, _ = targets[0]
                
                # Send to all target groups
                for target in targets:
                    _, _, _, _, chat_id, thread_id, delay = target
                    
                    success, message = await self.send_promotion_message(
                        user_id, chat_id, message_text, media_path, thread_id, delay
                    )
                    
                    # Log statistics
                    with sqlite3.connect(self.db.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO statistics (campaign_id, chat_id, sent_at, status, error_message)
                            VALUES (?, ?, datetime('now'), ?, ?)
                        ''', (campaign_id, chat_id, 
                              'success' if success else 'failed', 
                              message if not success else None))
                        conn.commit()
                
                # Wait for next interval
                await asyncio.sleep(interval * 60)
                
            except Exception as e:
                logger.error(f"Error in campaign {campaign_id}: {e}")
                await asyncio.sleep(60)
    
    async def start_campaign(self, campaign_id: int):
        """Start a campaign"""
        if campaign_id in self.active_campaigns:
            return False, "Kampanye sudah berjalan"
        
        task = asyncio.create_task(self.run_campaign(campaign_id))
        self.active_campaigns[campaign_id] = task
        return True, "Kampanye dimulai"
    
    async def stop_campaign(self, campaign_id: int):
        """Stop a campaign"""
        if campaign_id in self.active_campaigns:
            self.active_campaigns[campaign_id].cancel()
            del self.active_campaigns[campaign_id]
            return True, "Kampanye dihentikan"
        return False, "Kampanye tidak ditemukan"
    
    async def stop_all(self):
        """Stop all userbots and campaigns"""
        self.is_running = False
        for task in self.active_campaigns.values():
            task.cancel()
        self.active_campaigns.clear()
        
        for app in self.userbots.values():
            try:
                await app.stop()
            except:
                pass
        self.userbots.clear()

# ============================ CONTROL BOT ============================

class ControlBot:
    def __init__(self, token: str, userbot_manager: UserBotManager):
        self.token = token
        self.manager = userbot_manager
        self.db = userbot_manager.db
        self.application = Application.builder().token(token).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup command handlers"""
        # Start command
        self.application.add_handler(CommandHandler("start", self.start_command))
        
        # Setup commands
        self.application.add_handler(CommandHandler("setup", self.setup_command))
        self.application.add_handler(CommandHandler("add_campaign", self.add_campaign_command))
        self.application.add_handler(CommandHandler("add_group", self.add_group_command))
        self.application.add_handler(CommandHandler("start_campaign", self.start_campaign_command))
        self.application.add_handler(CommandHandler("stop_campaign", self.stop_campaign_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("trial", self.trial_command))
        
        # Callback query handler for inline keyboards
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        
        # Message handler for processing setup
        self.application.add_handler(MessageHandler(
            tg_filters.TEXT & ~tg_filters.COMMAND, 
            self.message_handler
        ))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        welcome_text = """
🤖 **Telegram UserBot Promosi Otomatis**

Fitur Utama:
✅ Promosi otomatis ke grup/chat
✅ Pengaturan timer penjadwalan
✅ Dikontrol oleh akun lain
✅ Text berbeda untuk grup berbeda
✅ Privasi 100% (settingan Anda sendiri)
✅ Minim delay
✅ Trial available
✅ Unlimited tanpa fee
✅ Support media & hyperlink
✅ Support grup dengan topik

Gunakan perintah:
/setup - Setup UserBot Anda
/add_campaign - Buat kampanye baru
/add_group - Tambah grup target
/start_campaign - Mulai kampanye
/stop_campaign - Hentikan kampanye
/stats - Lihat statistik
/trial - Coba trial 24 jam
        """
        
        keyboard = [
            [InlineKeyboardButton("🎬 Video Tutorial", url="https://example.com/tutorial")],
            [InlineKeyboardButton("🆓 Trial 24 Jam", callback_data="trial_start")],
            [InlineKeyboardButton("💳 Beli Akses", callback_data="buy_access")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def setup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setup command for UserBot configuration"""
        user_id = update.effective_user.id
        
        setup_text = """
📋 **Setup UserBot Anda**

Langkah 1: Dapatkan API ID & Hash
1. Buka https://my.telegram.org
2. Login dengan akun Telegram Anda
3. Buat aplikasi baru
4. Copy API ID dan API Hash

Langkah 2: Kirim dalam format:
`api_id api_hash`

Contoh: `1234567 a1b2c3d4e5f67890abcdef`
        """
        
        await update.message.reply_text(setup_text, parse_mode='Markdown')
        context.user_data['awaiting_api'] = True
    
    async def add_campaign_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_campaign command"""
        user_id = update.effective_user.id
        
        campaign_text = """
📢 **Buat Kampanye Promosi Baru**

Kirim dalam format:
`nama_kampanye|pesan|interval_menit`

Contoh:
`Promo Toko|Halo! Belanja di toko kami...|60`

Untuk menambahkan media, kirim file/gambar setelahnya.
        """
        
        await update.message.reply_text(campaign_text)
        context.user_data['awaiting_campaign'] = True
    
    async def add_group_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_group command"""
        user_id = update.effective_user.id
        
        group_text = """
👥 **Tambahkan Grup Target**

Langkah:
1. Tambahkan UserBot ke grup Anda
2. Forward pesan apa saja dari grup ke bot ini
3. Atau kirim ID grup dalam format:
`campaign_id|chat_id|thread_id|delay_detik`

thread_id: 0 untuk tanpa topik, atau ID topik tertentu
        """
        
        await update.message.reply_text(group_text)
        context.user_data['awaiting_group'] = True
    
    async def start_campaign_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_campaign command"""
        if context.args:
            campaign_id = int(context.args[0])
            success, message = await self.manager.start_campaign(campaign_id)
            await update.message.reply_text(f"📤 {message}")
        else:
            await update.message.reply_text("Gunakan: /start_campaign campaign_id")
    
    async def stop_campaign_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_campaign command"""
        if context.args:
            campaign_id = int(context.args[0])
            success, message = await self.manager.stop_campaign(campaign_id)
            await update.message.reply_text(f"🛑 {message}")
        else:
            await update.message.reply_text("Gunakan: /stop_campaign campaign_id")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user_id = update.effective_user.id
        
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            # Get campaign stats
            cursor.execute('''
                SELECT c.name, COUNT(s.id), 
                       SUM(CASE WHEN s.status = 'success' THEN 1 ELSE 0 END)
                FROM campaigns c
                LEFT JOIN statistics s ON c.id = s.campaign_id
                WHERE c.user_id = ?
                GROUP BY c.id
            ''', (user_id,))
            
            stats = cursor.fetchall()
        
        if not stats:
            await update.message.reply_text("📊 Belum ada statistik")
            return
        
        stats_text = "📊 **Statistik Kampanye**\n\n"
        for name, total, success in stats:
            stats_text += f"**{name}**\n"
            stats_text += f"  ✅ Berhasil: {success or 0}\n"
            stats_text += f"  📤 Total: {total or 0}\n\n"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def trial_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trial command for 24-hour trial"""
        user_id = update.effective_user.id
        
        # Check if already in trial
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM trial_users 
                WHERE user_id = ? AND is_active = 1 AND end_time > datetime('now')
            ''', (user_id,))
            result = cursor.fetchone()
        
        if result[0] > 0:
            await update.message.reply_text("🎁 Anda sudah memiliki trial aktif!")
            return
        
        # Add trial user
        start_time = datetime.now()
        end_time = start_time + timedelta(days=1)
        
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trial_users (user_id, start_time, end_time, is_active)
                VALUES (?, ?, ?, 1)
            ''', (user_id, start_time.isoformat(), end_time.isoformat()))
            conn.commit()
        
        trial_text = f"""
🎉 **Trial 24 Jam Aktif!**

Trial aktif dari:
{start_time.strftime('%Y-%m-%d %H:%M')}
Sampai:
{end_time.strftime('%Y-%m-%d %H:%M')}

Gunakan /setup untuk mulai konfigurasi!
        """
        
        await update.message.reply_text(trial_text)
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "trial_start":
            await self.trial_command(update, context)
        elif query.data == "buy_access":
            await self.show_payment_options(query)
    
    async def show_payment_options(self, query: CallbackQuery):
        """Show payment options"""
        keyboard = [
            [InlineKeyboardButton("💰 1 Bulan - Rp 50.000", callback_data="buy_1month")],
            [InlineKeyboardButton("💎 3 Bulan - Rp 120.000", callback_data="buy_3month")],
            [InlineKeyboardButton("👑 1 Tahun - Rp 400.000", callback_data="buy_1year")],
            [InlineKeyboardButton("🔄 Lifetime - Rp 1.000.000", callback_data="buy_lifetime")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        payment_text = """
💳 **Pilih Paket Akses**

💰 **1 Bulan** - Rp 50.000
💎 **3 Bulan** - Rp 120.000 (hemat 20%)
👑 **1 Tahun** - Rp 400.000 (hemat 33%)
🔄 **Lifetime** - Rp 1.000.000 (sekali bayar)

✅ Semua paket mendapatkan:
   • Fitur unlimited
   • Update gratis
   • Support 24/7
   • Garansi 100%
        """
        
        await query.edit_message_text(payment_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular messages for setup"""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        if context.user_data.get('awaiting_api'):
            try:
                parts = message_text.split()
                if len(parts) == 2:
                    api_id = int(parts[0])
                    api_hash = parts[1]
                    
                    # Save to database
                    self.db.add_user(user_id, api_id, api_hash, "")
                    
                    # Create userbot
                    await self.manager.create_userbot(user_id, api_id, api_hash, "")
                    
                    await update.message.reply_text("✅ API berhasil disimpan! UserBot diaktifkan.")
                else:
                    await update.message.reply_text("❌ Format salah. Gunakan: api_id api_hash")
                
                context.user_data['awaiting_api'] = False
                
            except ValueError:
                await update.message.reply_text("❌ API ID harus berupa angka")
        
        elif context.user_data.get('awaiting_campaign'):
            try:
                parts = message_text.split('|')
                if len(parts) >= 3:
                    campaign_name = parts[0]
                    message_text_campaign = parts[1]
                    interval = int(parts[2])
                    
                    # Save campaign to database
                    with sqlite3.connect(self.db.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO campaigns (user_id, name, message_text, interval_minutes, is_active)
                            VALUES (?, ?, ?, ?, 1)
                        ''', (user_id, campaign_name, message_text_campaign, interval))
                        campaign_id = cursor.lastrowid
                        conn.commit()
                    
                    await update.message.reply_text(
                        f"✅ Kampanye '{campaign_name}' dibuat (ID: {campaign_id})!\n"
                        f"Sekarang tambahkan grup dengan /add_group"
                    )
                else:
                    await update.message.reply_text("❌ Format salah")
                
                context.user_data['awaiting_campaign'] = False
                
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        
        elif context.user_data.get('awaiting_group'):
            if update.message.forward_from_chat:
                # Group from forwarded message
                chat = update.message.forward_from_chat
                chat_id = chat.id
                chat_title = chat.title
                
                await update.message.reply_text(
                    f"✅ Grup terdeteksi:\n"
                    f"Nama: {chat_title}\n"
                    f"ID: {chat_id}\n\n"
                    f"Kirim: campaign_id|{chat_id}|thread_id|delay\n"
                    f"Contoh: 1|{chat_id}|0|30"
                )
            else:
                try:
                    parts = message_text.split('|')
                    if len(parts) == 4:
                        campaign_id = int(parts[0])
                        chat_id = int(parts[1])
                        thread_id = int(parts[2])
                        delay = int(parts[3])
                        
                        # Get chat info
                        try:
                            # Try to get chat info using userbot
                            userbot = self.manager.userbots.get(user_id)
                            if userbot:
                                chat = await userbot.get_chat(chat_id)
                                chat_title = chat.title
                            else:
                                chat_title = "Unknown Group"
                        except:
                            chat_title = "Unknown Group"
                        
                        # Save to database
                        with sqlite3.connect(self.db.db_path) as conn:
                            cursor = conn.cursor()
                            cursor.execute('''
                                INSERT INTO target_groups (campaign_id, chat_id, chat_title, thread_id, delay_seconds, is_active)
                                VALUES (?, ?, ?, ?, ?, 1)
                            ''', (campaign_id, chat_id, chat_title, thread_id, delay))
                            conn.commit()
                        
                        await update.message.reply_text(
                            f"✅ Grup ditambahkan ke kampanye {campaign_id}!\n"
                            f"Gunakan /start_campaign {campaign_id} untuk memulai"
                        )
                    else:
                        await update.message.reply_text("❌ Format salah")
                    
                    context.user_data['awaiting_group'] = False
                    
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def run(self):
        """Start the control bot"""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("🤖 Control Bot started!")
        
        # Keep running
        try:
            await asyncio.Future()  # Run forever
        except (KeyboardInterrupt, SystemExit):
            await self.application.stop()

# ============================ MAIN APPLICATION ============================

class TelegramPromotionBot:
    def __init__(self, control_bot_token: str):
        self.manager = UserBotManager()
        self.control_bot = ControlBot(control_bot_token, self.manager)
        self.is_running = False
    
    async def start(self):
        """Start both userbots and control bot"""
        self.is_running = True
        
        logger.info("🚀 Starting Telegram Promotion Bot...")
        
        # Initialize all userbots from database
        await self.manager.initialize_all_userbots()
        
        # Start control bot
        control_task = asyncio.create_task(self.control_bot.run())
        
        # Keep running
        try:
            await asyncio.gather(control_task)
        except KeyboardInterrupt:
            await self.stop()
    
    async def stop(self):
        """Stop everything"""
        self.is_running = False
        await self.manager.stop_all()
        logger.info("🛑 Bot stopped")

# ============================ CONFIGURATION ============================

def load_config():
    """Load configuration from file or environment"""
    config_path = Path("config.json")
    
    if config_path.exists():
        with open(config_path, 'r') as f:
            return json.load(f)
    else:
        # Create default config
        default_config = {
            "control_bot_token": "5593144463:AAFsIwRgGoGXEBQC-kZibnMoMV5BkRwjqIA",
            "admin_user_ids": [5166575484],  # Your Telegram user ID
            "max_messages_per_day": 100,
            "default_delay_seconds": 30,
            "trial_duration_hours": 24
        }
        
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=4)
        
        print("⚠️ Config file created. Please edit config.json")
        return default_config

# ============================ RUN BOT ============================

async def main():
    """Main function"""
    # Load configuration
    config = load_config()
    
    if config["control_bot_token"] == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set your bot token in config.json")
        print("Get token from @BotFather on Telegram")
        return
    
    # Create and start bot
    bot = TelegramPromotionBot(config["control_bot_token"])
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        await bot.stop()

if __name__ == "__main__":
    # Check requirements
    try:
        import pyrogram
        import telegram
    except ImportError:
        print("❌ Requirements not installed!")
        print("Install with: pip install pyrogram python-telegram-bot")
        exit(1)
    
    # Run the bot
    asyncio.run(main())
