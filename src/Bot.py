import os
import logging
import asyncio
import json
from coinbase.rest import RESTClient
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes
# from coinbase.wallet.client import Client as CoinbaseClient

from coinbase.wallet.error import APIError
import requests
from requests.exceptions import RequestException
import time

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class Bot:
    def __init__(self):
        # Use environment variables for sensitive data
        self.token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.username = os.environ.get('TELEGRAM_BOT_USERNAME')
        coinbase_api_key = os.getenv('COINBASE_API_KEY')
        coinbase_api_secret = os.getenv('COINBASE_API_SECRET')
        
        print(f"API Key: {coinbase_api_key[:4]}...")  # Print the first few characters only
        print(f"API Secret: {coinbase_api_secret[:4]}...")



        if not all([self.token, self.username, coinbase_api_key, coinbase_api_secret]):
            raise ValueError("Missing environment variables. Please set all required variables.")

        self.coinbase_client = RESTClient(api_key=coinbase_api_key, api_secret=coinbase_api_secret)
        # accounts = self.coinbase_client.get_accounts()
        # print(json.dumps(accounts, indent=2))
        # Test API connection
        # if not self.test_api_connection():
        #     raise ValueError("Failed to connect to Coinbase API. Please check your credentials.")

        # Create the application with the bot's token
        self.application = Application.builder().token(self.token).build()
        
        # Register command handlers
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('trades', self.get_trades))
        self.application.add_handler(CommandHandler('subscribe', self.subscribe))
        self.application.add_handler(CommandHandler('unsubscribe', self.unsubscribe))
        
        # Register a handler for all text messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_update_received))



        # Background tasks
        self.background_tasks = set()

        # Subscription management
        self.subscribed_chats = set()
        self.load_subscriptions()

        # Last posted trade tracking
        self.last_posted_trade_id = None
        self.load_last_posted_trade_id()

    async def on_update_received(self, update: Update, context):
        """Process incoming updates (messages)."""
        logger.info(f"Received update: {update}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="I received your message!")

    async def start(self, update: Update, context):
        """Handle the /start command."""
        await context.bot.send_message(chat_id=update.effective_chat.id, 
                                       text="Hello! I'm your Coinbase trading bot. Use /subscribe to get trade updates.")

    async def get_trades(self, update: Update, context):
        """Fetch and display recent trades from Coinbase."""
        try:
            accounts = self.coinbase_client.get_accounts()
            btc_account = next((account for account in accounts.data if account['currency'] == 'BTC'), None)
            
            if btc_account:
                transactions = self.coinbase_client.get_transactions(btc_account['id'])
                if transactions.data:
                    message = "Recent BTC transactions:\n"
                    for tx in transactions.data[:5]:  # Limit to 5 transactions
                        message += self.format_transaction(tx)
                else:
                    message = "No recent BTC transactions found."
            else:
                message = "No BTC account found."
            
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message)
        except APIError as e:
            logger.error(f"Coinbase API error in get_trades: {str(e)}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Error fetching trades: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in get_trades: {str(e)}", exc_info=True)
            await context.bot.send_message(chat_id=update.effective_chat.id, text="An unexpected error occurred. Please try again later.")

    async def subscribe(self, update: Update, context):
        """Subscribe a user to trade updates."""
        chat_id = update.effective_chat.id
        if chat_id not in self.subscribed_chats:
            self.subscribed_chats.add(chat_id)
            self.save_subscriptions()
            await context.bot.send_message(chat_id=chat_id, text="You've been subscribed to trade updates!")
        else:
            await context.bot.send_message(chat_id=chat_id, text="You're already subscribed to trade updates.")

    async def unsubscribe(self, update: Update, context):
        """Unsubscribe a user from trade updates."""
        chat_id = update.effective_chat.id
        if chat_id in self.subscribed_chats:
            self.subscribed_chats.remove(chat_id)
            self.save_subscriptions()
            await context.bot.send_message(chat_id=chat_id, text="You've been unsubscribed from trade updates.")
        else:
            await context.bot.send_message(chat_id=chat_id, text="You're not currently subscribed to trade updates.")

    async def check_and_post_new_trades(self):
        """Periodically check for new trades and post them."""
        while True:
            try:
                accounts = self.get_accounts_with_retry()
                
                if not accounts:
                    logger.error("Failed to retrieve accounts after multiple attempts")
                    await asyncio.sleep(60)
                    continue

                btc_account = next((account for account in accounts['data'] if account['currency'] == 'BTC'), None)
                
                if btc_account:
                    transactions = self.get_transactions_with_retry(btc_account['id'])
                    
                    if not transactions:
                        logger.error("Failed to retrieve transactions after multiple attempts")
                        await asyncio.sleep(60)
                        continue

                    new_transactions = [tx for tx in transactions['data'] if self.is_new_transaction(tx)]
                    
                    if new_transactions:
                        message = "New BTC transactions:\n"
                        for tx in new_transactions[:5]:  # Limit to 5 transactions
                            message += self.format_transaction(tx)
                        
                        self.update_last_posted_trade_id(new_transactions[0]['id'])
                        
                        for chat_id in self.subscribed_chats:
                            await self.application.bot.send_message(chat_id=chat_id, text=message)
                else:
                    logger.warning("No BTC account found")
            
            except Exception as e:
                logger.error(f"Unexpected error in check_and_post_new_trades: {str(e)}", exc_info=True)
            
            await asyncio.sleep(60)  # Check every minute

    def get_accounts_with_retry(self, max_retries=3, delay=5):
        """Attempt to get accounts with retries."""
        for attempt in range(max_retries):
            try:
                response = self.coinbase_client._get('v2', 'accounts')
                response.raise_for_status()  # Raise an exception for bad status codes
                return response.json()
            except RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    logger.error("Max retries reached. Unable to fetch accounts.")
                    return None

    def get_transactions_with_retry(self, account_id, max_retries=3, delay=5):
        """Attempt to get transactions with retries."""
        for attempt in range(max_retries):
            try:
                response = self.coinbase_client._get('v2', 'accounts', account_id, 'transactions')
                response.raise_for_status()  # Raise an exception for bad status codes
                return response.json()
            except RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    logger.error("Max retries reached. Unable to fetch transactions.")
                    return None

    def format_transaction(self, tx):
        """Format a single transaction for display."""
        return f"Type: {tx['type']}, Amount: {tx['amount']['amount']} {tx['amount']['currency']}, " \
               f"Status: {tx['status']}, Date: {tx['created_at']}\n"

    def is_new_transaction(self, transaction):
        """Check if a transaction is new based on its ID."""
        if self.last_posted_trade_id is None:
            return True
        return transaction['id'] > self.last_posted_trade_id

    def update_last_posted_trade_id(self, trade_id):
        """Update the last posted trade ID."""
        self.last_posted_trade_id = trade_id
        self.save_last_posted_trade_id()

    def save_last_posted_trade_id(self):
        """Save the last posted trade ID to a file."""
        try:
            with open('last_trade_id.json', 'w') as f:
                json.dump({'last_trade_id': self.last_posted_trade_id}, f)
        except Exception as e:
            logger.error(f"Failed to save last trade ID: {str(e)}")

    def load_last_posted_trade_id(self):
        """Load the last posted trade ID from a file."""
        try:
            if os.path.exists('last_trade_id.json'):
                with open('last_trade_id.json', 'r') as f:
                    data = json.load(f)
                    self.last_posted_trade_id = data.get('last_trade_id')
        except Exception as e:
            logger.error(f"Failed to load last trade ID: {str(e)}")

    def save_subscriptions(self):
        """Save the set of subscribed chat IDs to a file."""
        try:
            with open('subscriptions.json', 'w') as f:
                json.dump(list(self.subscribed_chats), f)
        except Exception as e:
            logger.error(f"Failed to save subscriptions: {str(e)}")

    def load_subscriptions(self):
        """Load the set of subscribed chat IDs from a file."""
        try:
            if os.path.exists('subscriptions.json'):
                with open('subscriptions.json', 'r') as f:
                    self.subscribed_chats = set(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load subscriptions: {str(e)}")

    async def start_background_tasks(self):
        self.background_tasks.add(asyncio.create_task(self.check_and_post_new_trades()))

    async def start_bot(self):
        await self.start_background_tasks()
        await self.application.initialize()
        await self.application.start()
        self.application.updater.start_polling()
        await self.application.updater.idle()  # Ensure the bot keeps running

    def run(self):
        """Start the bot and background tasks."""
        asyncio.run(self.start_bot())

    # def test_api_connection(self):
        # try:
        #     response = self.coinbase_client._get('v2', 'user')
        #     logger.debug(f"Test API response status: {response.status_code}")
        #     logger.debug(f"Test API response text: {response.text}")
        #     return response.json()
        # except APIError as e:
        #     logger.error(f"APIError: {e}")
        #     return None
        # except Exception as e:
        #     logger.error(f"Unexpected error: {str(e)}")
        #     return None
        
    


if __name__ == "__main__":
    bot = Bot()
    bot.run()
