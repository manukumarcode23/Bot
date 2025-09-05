# Telegram Video Streaming System using Pyrogram/Pyrofork
# pip install pyrogram tgcrypto aiofiles flask

import asyncio
import os
import aiofiles
from pyrogram import Client, filters
from pyrogram.types import Message
import logging
from flask import Flask, Response, request, render_template_string
import threading
import io
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramVideoStreamer:
    def __init__(self, api_id, api_hash, bot_token, storage_chat_id):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.storage_chat_id = storage_chat_id
        
        # Initialize Pyrogram client
        self.app = Client(
            "video_streamer_bot",
            api_id=api_id,
            api_hash=api_hash,
            bot_token=bot_token
        )
        
        # Video storage
        self.videos = {}  # {video_id: {file_id, file_name, size, duration}}
        
        # Flask app for streaming
        self.flask_app = Flask(__name__)
        self.setup_routes()
        
    def setup_routes(self):
        @self.flask_app.route('/')
        def index():
            return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Telegram Video Streamer</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    .video-item { margin: 20px 0; padding: 15px; border: 1px solid #ddd; }
                    video { max-width: 100%; height: auto; }
                </style>
            </head>
            <body>
                <h1>Telegram Video Streamer</h1>
                <div id="videos">
                    {% for video_id, video_info in videos.items() %}
                    <div class="video-item">
                        <h3>{{ video_info.file_name }}</h3>
                        <p>Size: {{ "%.2f"|format(video_info.size / (1024*1024)) }} MB</p>
                        <video controls width="640">
                            <source src="/stream/{{ video_id }}" type="video/mp4">
                            Your browser does not support video streaming.
                        </video>
                        <br>
                        <a href="/download/{{ video_id }}">Download</a>
                    </div>
                    {% endfor %}
                </div>
                
                <h2>Upload Video</h2>
                <form action="/upload" method="post" enctype="multipart/form-data">
                    <input type="file" name="video" accept="video/*" required>
                    <input type="submit" value="Upload to Telegram Storage">
                </form>
            </body>
            </html>
            """, videos=self.videos)
        
        @self.flask_app.route('/stream/<video_id>')
        def stream_video(video_id):
            if video_id not in self.videos:
                return "Video not found", 404
            
            return Response(
                self.generate_video_stream(video_id),
                mimetype='video/mp4',
                headers={
                    'Content-Type': 'video/mp4',
                    'Accept-Ranges': 'bytes'
                }
            )
        
        @self.flask_app.route('/download/<video_id>')
        def download_video(video_id):
            if video_id not in self.videos:
                return "Video not found", 404
            
            video_info = self.videos[video_id]
            
            def generate():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    async def download():
                        async for chunk in self.app.stream_media(video_info['file_id']):
                            yield chunk
                    
                    gen = download()
                    while True:
                        try:
                            chunk = loop.run_until_complete(gen.__anext__())
                            yield chunk
                        except StopAsyncIteration:
                            break
                finally:
                    loop.close()
            
            return Response(
                generate(),
                mimetype='application/octet-stream',
                headers={
                    'Content-Disposition': f'attachment; filename="{video_info["file_name"]}"'
                }
            )
    
    def generate_video_stream(self, video_id):
        """Generate video stream chunks for HTTP streaming"""
        try:
            video_info = self.videos[video_id]
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                async def stream():
                    async for chunk in self.app.stream_media(video_info['file_id']):
                        yield chunk
                
                # Stream the video
                gen = stream()
                while True:
                    try:
                        chunk = loop.run_until_complete(gen.__anext__())
                        yield chunk
                    except StopAsyncIteration:
                        break
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"Error streaming video {video_id}: {e}")
            yield b""
    
    async def upload_video_to_telegram(self, video_path, video_name):
        """Upload video to Telegram storage chat"""
        try:
            message = await self.app.send_video(
                chat_id=self.storage_chat_id,
                video=video_path,
                caption=f"📹 {video_name}",
                supports_streaming=True
            )
            
            video_id = str(message.id)
            video_file = message.video
            
            self.videos[video_id] = {
                'file_id': video_file.file_id,
                'file_name': video_name,
                'size': video_file.file_size,
                'duration': video_file.duration,
                'message_id': message.id
            }
            
            logger.info(f"Video uploaded: {video_name} (ID: {video_id})")
            return video_id
            
        except Exception as e:
            logger.error(f"Error uploading video: {e}")
            return None
    
    async def load_existing_videos(self):
        """Load existing videos from storage chat"""
        try:
            # First, send a connection test message
            try:
                logger.info(f"🔄 Testing connection to storage channel...")
                test_message = await self.app.send_message(
                    self.storage_chat_id, 
                    "✅ **Bot Connected Successfully!**\n\n"
                    "🤖 Video Streamer Bot is now active\n"
                    "📹 Ready to store and stream videos\n"
                    "🌐 Web interface: http://localhost:5000\n\n"
                    "**Status:** ONLINE ✨"
                )
                logger.info("✅ SUCCESS: Bot can send messages to storage channel!")
                logger.info("✅ DONE: Connection test completed successfully")
                
                # Keep the message for 10 seconds then delete
                await asyncio.sleep(10)
                try:
                    await test_message.delete()
                    logger.info("🧹 Cleaned up test message")
                except:
                    pass  # Don't worry if we can't delete
                    
            except Exception as e:
                logger.error(f"❌ FAILED: Cannot send messages to storage channel: {e}")
                logger.error("❌ Bot connection test FAILED")
                return
            
            # Now try to get chat info and load videos
            try:
                chat = await self.app.get_chat(self.storage_chat_id)
                logger.info(f"📱 Connected to: {chat.title or chat.first_name}")
                
                # Load existing videos from channel history
                video_count = 0
                logger.info("🔍 Scanning channel for existing videos...")
                
                async for message in self.app.get_chat_history(self.storage_chat_id, limit=100):
                    if message.video:
                        video_id = str(message.id)
                        video_file = message.video
                        
                        self.videos[video_id] = {
                            'file_id': video_file.file_id,
                            'file_name': video_file.file_name or f"video_{video_id}.mp4",
                            'size': video_file.file_size,
                            'duration': video_file.duration,
                            'message_id': message.id
                        }
                        video_count += 1
                
                logger.info(f"📹 Found and loaded {video_count} existing videos")
                
                # Send final status message
                status_message = await self.app.send_message(
                    self.storage_chat_id,
                    f"📊 **System Status Report**\n\n"
                    f"✅ Bot: Online\n"
                    f"📹 Videos found: {video_count}\n"
                    f"🌐 Web server: Running on port 5000\n"
                    f"⚡ Status: Ready for streaming\n\n"
                    f"**DONE** - All systems operational! 🚀"
                )
                
                # Delete status message after 15 seconds
                await asyncio.sleep(15)
                try:
                    await status_message.delete()
                except:
                    pass
                    
            except Exception as e:
                logger.warning(f"Could not load chat history: {e}")
            
        except Exception as e:
            logger.error(f"Error in load_existing_videos: {e}")
    
    def setup_bot_handlers(self):
        """Setup Pyrogram event handlers"""
        
        @self.app.on_message(filters.video & filters.private)
        async def handle_video_upload(client, message: Message):
            """Handle direct video uploads to bot"""
            try:
                # Forward to storage chat
                forwarded = await message.forward(self.storage_chat_id)
                
                video_id = str(forwarded.id)
                video_file = message.video
                
                self.videos[video_id] = {
                    'file_id': video_file.file_id,
                    'file_name': video_file.file_name or f"video_{video_id}.mp4",
                    'size': video_file.file_size,
                    'duration': video_file.duration,
                    'message_id': forwarded.id
                }
                
                await message.reply_text(
                    f"✅ Video uploaded successfully!\n"
                    f"📹 Name: {self.videos[video_id]['file_name']}\n"
                    f"💾 Size: {self.videos[video_id]['size'] / (1024*1024):.2f} MB\n"
                    f"🔗 Stream URL: http://localhost:5000/stream/{video_id}"
                )
                
            except Exception as e:
                logger.error(f"Error handling video upload: {e}")
                await message.reply_text("❌ Error uploading video.")
        
        @self.app.on_message(filters.command("start"))
        async def start_command(client, message):
            user_name = message.from_user.first_name or "User"
            welcome_message = (
                f"🎬 **Welcome {user_name}!**\n\n"
                "🤖 **Telegram Video Streamer Bot**\n"
                "Send me a video file and I'll store it and provide streaming links!\n\n"
                "**📋 Commands:**\n"
                "• `/start` - Show this welcome message\n"
                "• `/list` - List all stored videos\n"
                "• `/help` - Show detailed help\n"
                "• `/status` - Check bot status\n\n"
                "**🌐 Web Interface:**\n"
                "• View: http://localhost:5000\n"
                "• Stream videos directly in browser\n"
                "• Download videos\n\n"
                "**📤 How to use:**\n"
                "1. Send me any video file\n"
                "2. I'll store it in the channel\n"
                "3. Get streaming links instantly!\n\n"
                "✨ **Ready to receive videos!**"
            )
            await message.reply_text(welcome_message)
            
        @self.app.on_message(filters.command("status"))
        async def status_command(client, message):
            video_count = len(self.videos)
            status_text = (
                "📊 **Bot Status Report**\n\n"
                f"🤖 Bot: ✅ Online\n"
                f"📹 Videos stored: {video_count}\n"
                f"💾 Storage: Channel 'Cfg'\n"
                f"🌐 Web server: ✅ Running\n"
                f"⚡ Streaming: ✅ Active\n\n"
                "**All systems operational!** 🚀"
            )
            await message.reply_text(status_text)
        
        @self.app.on_message(filters.command("list"))
        async def list_videos(client, message):
            if not self.videos:
                await message.reply_text("No videos stored yet.")
                return
            
            video_list = "📹 **Stored Videos:**\n\n"
            for video_id, info in self.videos.items():
                video_list += (
                    f"🎬 **{info['file_name']}**\n"
                    f"💾 Size: {info['size'] / (1024*1024):.2f} MB\n"
                    f"⏱ Duration: {info['duration']}s\n"
                    f"🔗 Stream: /stream_{video_id}\n\n"
                )
            
            await message.reply_text(video_list)
    
    async def start_bot(self):
        """Start the Telegram bot"""
        await self.app.start()
        logger.info("Bot started successfully")
        
        # Load existing videos
        await self.load_existing_videos()
        
        # Keep the bot running using asyncio.Event
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            logger.info("Shutting down bot...")
        finally:
            await self.app.stop()
    
    def start_flask_server(self):
        """Start Flask server in a separate thread"""
        self.flask_app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    
    def run(self):
        """Run the complete streaming system"""
        # Setup bot handlers
        self.setup_bot_handlers()
        
        # Start Flask server in background thread
        flask_thread = threading.Thread(target=self.start_flask_server)
        flask_thread.daemon = True
        flask_thread.start()
        
        # Start the bot
        logger.info("Starting Telegram Video Streamer...")
        logger.info("Web interface will be available at: http://localhost:5000")
        
        asyncio.run(self.start_bot())

# Usage example
if __name__ == "__main__":
    # Configuration with your credentials
    API_ID = 25929889
    API_HASH = "fd980dbd069e0b45d0dec91f7e616bad"
    BOT_TOKEN = "8492028054:AAHErmHeCi2psVuRuY7WPVTWw5gYsci3Fpc"
    STORAGE_CHAT_ID = "-1003096326174"  # Your "Cfg" channel
    
    # Create and run the streamer
    streamer = TelegramVideoStreamer(API_ID, API_HASH, BOT_TOKEN, STORAGE_CHAT_ID)
    
    try:
        streamer.run()
    except KeyboardInterrupt:
        print("\n👋 Shutting down gracefully...")
    except Exception as e:
        print(f"❌ Error: {e}")

# Additional utility functions
class VideoManager:
    """Additional utilities for video management"""
    
    @staticmethod
    async def get_video_info(file_path):
        """Get video information"""
        try:
            import ffmpeg
            probe = ffmpeg.probe(file_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            
            return {
                'duration': float(probe['format']['duration']),
                'width': video_info['width'],
                'height': video_info['height'],
                'fps': eval(video_info['r_frame_rate']),
                'codec': video_info['codec_name']
            }
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None
    
    @staticmethod
    async def compress_video(input_path, output_path, quality='medium'):
        """Compress video for better streaming"""
        try:
            import ffmpeg
            
            quality_settings = {
                'low': {'crf': 28, 'preset': 'fast'},
                'medium': {'crf': 23, 'preset': 'medium'},
                'high': {'crf': 18, 'preset': 'slow'}
            }
            
            settings = quality_settings.get(quality, quality_settings['medium'])
            
            (
                ffmpeg
                .input(input_path)
                .output(
                    output_path,
                    vcodec='libx264',
                    acodec='aac',
                    crf=settings['crf'],
                    preset=settings['preset'],
                    movflags='faststart'
                )
                .overwrite_output()
                .run()
            )
            
            return True
        except Exception as e:
            logger.error(f"Error compressing video: {e}")
            return False