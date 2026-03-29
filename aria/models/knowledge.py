"""Pydantic v2 models for the knowledge base and feature parity tools."""

from typing import Optional
from pydantic import BaseModel, ConfigDict


class KnowledgeArticle(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    article_id: str
    title: str
    category: str
    summary: str
    content: str
    self_service_channels: list[str]   # e.g. ["mobile", "web", "branch", "phone"]
    related_article_ids: list[str] = []


class KnowledgeSearchResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str
    matched: bool
    articles: list[KnowledgeArticle]
    suggestion: Optional[str] = None   # ARIA hint when no exact match


class ChannelFeature(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    feature_id: str
    feature_name: str
    feature_area: str           # e.g. digital_wallet, card_management, payments
    available_web: bool
    web_journey: Optional[str] = None      # step-by-step if available on web
    available_mobile: bool
    mobile_journey: Optional[str] = None   # step-by-step if available on mobile
    available_branch: bool = False
    available_phone: bool = False
    notes: Optional[str] = None


class FeatureParityResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    feature_area: str
    features: list[ChannelFeature]
    total_features: int
    web_only_count: int
    mobile_only_count: int
    both_count: int
    neither_count: int
