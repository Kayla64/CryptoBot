from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes
from coinbase.wallet.client import Client
import logging

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

class Bot:
    def __init__(self, token, username, coinbase_api_key, coinbase_api_secret):
        self.token = token
        self.username = username
        self.coinbase_client = Client(coinbase_api_key, coinbase_api_secret)

        # Create the application with the bot's token
        self.application = Application.builder().token(self.token).build()
        
        # Register command handlers
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('dadonly', self.dadonly))
        self.application.add_handler(CommandHandler('trades', self.get_trades))
        
        # Register a handler for all text messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_update_received))

    def get_bot_username(self):
        """Return the bot's username."""
        return self.username

    def get_bot_token(self):
        """Return the bot's token."""
        return self.token

    async def on_update_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming updates (messages)."""
        logging.info(f"Received update: {update}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="I received your message!")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /start command."""
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sup! I'm your Coinbase trading bot.")

    async def dadonly(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /dadonly command."""
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello dad")

    async def get_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fetch and display recent trades from Coinbase."""
        try:
            trades = self.coinbase_client.get_trades(product_id='BTC-USD')
            
            if trades:
                message = "Recent trades:\n"
                for trade in trades[:5]:  # Limit to 5 trades for brevity
                    message += f"Price: {trade['price']}, Size: {trade['size']}, Side: {trade['side']}\n"
            else:
                message = "No recent trades found."
            
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message)
        except Exception as e:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Error fetching trades: {str(e)}")

    def run(self):
        """Start the bot."""
        self.application.run_polling()


if __name__ == "__main__":
    # Bot and API credentials (replace with your actual credentials)
    TOKEN = '7371404329:AAHJ63cuthhm6Dy36cHgUbI5xnOQv8Stt40'  
    USERNAME = 'KayCryptoBot' 
    COINBASE_API_KEY = 'a7b7dc5a-5c0f-434b-a8fb-b97204f89a39'
    COINBASE_API_SECRET = 'MHcCAQEEIJXCEsXlKvrv0nUl83NOlEV8l9LdpBg8F3Q3Dmr6qcVioAoGCCqGSM49\nAwEHoUQDQgAEJUUlusaooMvgGxO850zHm4kGHqIKikf4jzhj/MVrNsIpidJceoPq\nv6ZY+wJDuJwegyT0FPQGsF2o3B2xHmCrKA=='

    # Create and run the bot
    bot = Bot(TOKEN, USERNAME, COINBASE_API_KEY, COINBASE_API_SECRET)
    bot.run()