"""
Base Agent Interface and Contract
"""
from abc import ABC, abstractmethod
from data.schema import FeatureSnapshot, AgentOutput


class BaseAgent(ABC):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    @abstractmethod
    def evaluate(self, snapshot: FeatureSnapshot) -> AgentOutput:
        """
        Evaluate feature snapshot and return standard AgentOutput
        """
        pass
