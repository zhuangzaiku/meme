class FakeAdapter:
    def __init__(self, chain_id: int) -> None:
        self.chain_id = chain_id

    async def get_chain_id(self) -> int:
        return self.chain_id
