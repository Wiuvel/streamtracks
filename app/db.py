from datetime import datetime
import logging
from sqlalchemy import Column, Integer, String, DateTime, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("db")
Base = declarative_base()

class Track(Base):
    __tablename__ = 'tracks'
    
    id = Column(Integer, primary_key=True)
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

    async def add_track(self, title: str, artist: str, spotify_id: str = None) -> bool:
        try:
            async with self.async_session() as session:
                stmt = select(Track).where(Track.title == title, Track.artist == artist)
                result = await session.execute(stmt)
                existing_track = result.scalars().first()
                
                if existing_track:
                    return False
                    
                new_track = Track(title=title, artist=artist, spotify_id=spotify_id)
                session.add(new_track)
                await session.commit()
                return True
        except Exception as e:
            logger.error(f"Database insertion error: {e}")
            return False
