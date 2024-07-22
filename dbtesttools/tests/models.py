import sqlalchemy as sa
from sqlalchemy.orm import declarative_base

ModelBase = declarative_base()


class TestModel(ModelBase):
    __tablename__ = "test_model"
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)
    value = sa.Column(sa.Integer)
