from sqlalchemy import JSON, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Url(Base):
    __tablename__ = "url"

    id = Column(Integer, primary_key=True)
    site = Column(String)
    url = Column(String)
    status = Column(Integer)
    metadata_json = Column(JSON, nullable=True)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class LinkMap(Base):
    __tablename__ = "link_map"

    id = Column(Integer, primary_key=True)
    site = Column(String)
    url = Column(String)
    link = Column(String)
