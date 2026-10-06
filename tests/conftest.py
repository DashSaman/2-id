import pytest
from app.crypto import derive_test_key
from app.db import Base, make_engine, make_session_factory


@pytest.fixture
def db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    yield sf
    engine.dispose()


@pytest.fixture
def crypto():
    from app.crypto import PayloadCrypto
    return PayloadCrypto(derive_test_key("test-seed"))
