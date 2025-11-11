from sqlalchemy import ARRAY, Boolean, Column, Integer, String, DateTime, ForeignKey, BigInteger, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

Base = declarative_base()

def utc_now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=utc_now)
    
    processed_images = relationship("ProcessedImage", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")


class ProcessedImage(Base):
    __tablename__ = "processed_images"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    image_key = Column(String, unique=True, nullable=False, index=True)
    

    original_file_id = Column(String, nullable=True)
    standard_transparent_file_id = Column(String, nullable=True)
    standard_bw_file_id = Column(String, nullable=True)
    improved_transparent_file_id = Column(String, nullable=True)
    improved_bw_file_id = Column(String, nullable=True)
    
    watermarked_transparent_file_id = Column(String, nullable=True)
    watermarked_bw_file_id = Column(String, nullable=True)
    watermarked_improved_transparent_file_id = Column(String, nullable=True)
    watermarked_improved_bw_file_id = Column(String, nullable=True)
    
    is_paid = Column(Boolean, default=False, nullable=False)
    
    improved_sent = Column(Boolean, default=False, nullable=False)
    discount_sent_290 = Column(Boolean, default=False, nullable=False)
    discount_sent_190 = Column(Boolean, default=False, nullable=False)
    discount_sent_99 = Column(Boolean, default=False, nullable=False)
    
    last_message_ids = Column(ARRAY(BigInteger), nullable=True)
    improved_message_ids = Column(ARRAY(BigInteger), nullable=True)
    discount_290_message_ids = Column(ARRAY(BigInteger), nullable=True)
    discount_190_message_ids = Column(ARRAY(BigInteger), nullable=True)
    discount_99_message_ids = Column(ARRAY(BigInteger), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=utc_now)
    
    user = relationship("User", back_populates="processed_images")
    payments = relationship("Payment", back_populates="processed_image")


class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    processed_image_id = Column(Integer, ForeignKey("processed_images.id", ondelete="SET NULL"), nullable=True)
    invoice_id = Column(String, unique=True, nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    status = Column(String, default="pending", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=utc_now)
    
    user = relationship("User", back_populates="payments")
    processed_image = relationship("ProcessedImage", back_populates="payments")
