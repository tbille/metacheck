from sqlalchemy import Column, Integer, String, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Url(Base):
    __tablename__ = "url"

    id = Column(Integer, primary_key=True)
    site = Column(String)
    url = Column(String)
    status = Column(Integer)
    metadata_json = Column(JSON, nullable=True)