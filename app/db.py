from datetime import datetime
import logging
from sqlalchemy import Column, Integer, String, DateTime, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("db")
Base = declarative_base()

class BotState(Base):
    __tablename__ = 'bot_state'
    
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)

class Track(Base):
    __tablename__ = 'tracks'
    
    id = Column(Integer, primary_key=True)
    stream_id = Column(String, nullable=True)
    title = Column(String, nullable=False)
    artist = Column(String, nullable=False)
    spotify_id = Column(String, nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow)

class Database:
    def __init__(self, db_path="sqlite+aiosqlite:////data/streamtracks.db"):
        self.engine = create_async_engine(db_path, echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init_db(self):
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.debug("Database initialized.")
        except Exception as e:
            logger.critical(f"Database initialization failed: {e}")

    async def get_state(self, key: str, default: str = None) -> str:
        try:
            async with self.async_session() as session:
                stmt = select(BotState).where(BotState.key == key)
                result = await session.execute(stmt)
                state = result.scalars().first()
                return state.value if state else default
        except Exception as e:
            logger.error(f"Error getting state {key}: {e}")
            return default

    async def set_state(self, key: str, value: str):
        try:
            async with self.async_session() as session:
                stmt = select(BotState).where(BotState.key == key)
                result = await session.execute(stmt)
                state = result.scalars().first()
                if state:
                    state.value = value
                else:
                    session.add(BotState(key=key, value=value))
                await session.commit()
        except Exception as e:
            logger.error(f"Error setting state {key}: {e}")

    async def add_track(self, title: str, artist: str, stream_id: str, spotify_id: str = None) -> bool:
        try:
            async with self.async_session() as session:
                # Deduplicate only within the SAME stream session
                stmt = select(Track).where(
                    Track.title == title, 
                    Track.artist == artist,
                    Track.stream_id == stream_id
                )
                result = await session.execute(stmt)
                existing_track = result.scalars().first()
                
                if existing_track:
                    return False
                    
                new_track = Track(title=title, artist=artist, stream_id=stream_id, spotify_id=spotify_id)
                session.add(new_track)
                await session.commit()
                return True
        except Exception as e:
            logger.error(f"Database insertion error: {e}")
            return False
