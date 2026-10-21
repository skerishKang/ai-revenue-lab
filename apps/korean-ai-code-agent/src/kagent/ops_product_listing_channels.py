"""#5446: declarative sales-channel listing profiles for the product-listing pilot.

Why this module exists
-----------------------
A sales channel's registration form is **data, not code**: field labels,
required-ness, length caps, allowed values and image rules change whenever the
channel changes its seller console. Encoding them as Python constants keeps the
projection engine (:mod:`kagent.ops_product_listing`) channel-agnostic, so a
channel update is a data edit and never a second authority, a second registry
or a new engine.

Every profile here is transcribed from the channel's own public seller
documentation. Each profile records the exact public URLs it was read from and
the date it was last checked, so a later reviewer can re-verify a claim instead
of trusting this file. No customer account, credential, contract price or
private business rule appears here.

Scope of the recorded rules
---------------------------
* Coupang: the 14-step Marketplace listing flow plus the Open API product
  creation field set.
* Naver Smart Store: the seller help-centre product-registration guidance.
* 11st: the seller-zone product-registration policy notices and the seller
  office manual.
* Own mall (Cafe24-style): the seller-console product-registration guide.

These profiles are a **pilot aid**, not a compliance certificate. A category
can carry additional mandatory notices, certificates and documents, so every
channel draft keeps an explicit "human confirmation required" outcome instead
of claiming the form is complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .ops_product_listing import (
    ChannelFieldKind,
    ChannelFieldSpec,
    ChannelImagePolicy,
    ChannelOptionPolicy,
    ChannelProfile,
    ProductAttribute,
)


COUPANG = "coupang"
NAVER_SMART_STORE = "naver_smart_store"
ELEVENST = "elevenst"
OWN_MALL = "own_mall"

PILOT_SOURCE_CHECKED_ON = "2026-10-21"


@dataclass(frozen=True, slots=True)
class ChannelImagePolicy:
    """Bounded image rules for one channel's registration form."""

    min_pixels: int
    recommended_pixels: int
    max_images: int
    max_bytes: int
    allowed_extensions: tuple[str, ...]
    square_required: bool
    note: str


@dataclass(frozen=True, slots=True)
class ChannelOptionPolicy:
    """Bounded option/attribute rules for one channel's registration form."""

    max_option_axes: int
    max_option_values_per_axis: int
    max_combinations: int
    option_name_max_chars: int
    option_value_max_chars: int
    note: str


def _text(
    key: str,
    label: str,
    source: ProductAttribute | None,
    *,
    required: bool = False,
    max_chars: int | None = None,
    kind: ChannelFieldKind = ChannelFieldKind.TEXT,
    allowed_values: tuple[str, ...] = (),
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    note: str = "",
) -> ChannelFieldSpec:
    return ChannelFieldSpec(
        key=key,
        label=label,
        source=source,
        required=required,
        max_chars=max_chars,
        kind=kind,
        allowed_values=allowed_values,
        minimum=minimum,
        maximum=maximum,
        note=note,
    )


COUPANG_PROFILE = ChannelProfile(
    channel_id=COUPANG,
    display_name="쿠팡 마켓플레이스",
    admin_surface="쿠팡 Wing > 상품관리 > 상품등록",
    fields=(
        _text("seller_product_name", "등록상품명", ProductAttribute.PRODUCT_NAME, required=True, max_chars=100),
        _text("display_product_name", "노출상품명", ProductAttribute.PRODUCT_NAME, max_chars=100),
        _text("category_code", "노출 카테고리 코드", ProductAttribute.CATEGORY_CODE, required=True, note="대분류/중분류/소분류 코드"),
        _text("brand", "브랜드", ProductAttribute.BRAND, required=True, note="브랜드 검색 후 선택, 미입력 시 노출 제한"),
        _text("manufacturer", "제조사", ProductAttribute.MANUFACTURER),
        _text("product_identifier", "상품 식별번호(품번/바코드)", ProductAttribute.PRODUCT_IDENTIFIER, required=True),
        _text("option_names", "구매옵션명", ProductAttribute.COLOR, note="최대 3개 옵션명, 옵션값은 콤마 구분"),
        _text("sale_price", "옵션 판매가", ProductAttribute.SALE_PRICE, required=True, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("10"), note="10원 단위"),
        _text("original_price", "정상가(할인율 기준가)", ProductAttribute.LIST_PRICE, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("stock_quantity", "총 재고수량", ProductAttribute.STOCK_QUANTITY, required=True, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("tax_type", "부가세 구분(Y/N)", ProductAttribute.TAX_TYPE, required=True, kind=ChannelFieldKind.ENUM, allowed_values=("Y", "N")),
        _text("minor_purchase_allowed", "미성년자 구매 가능 여부", ProductAttribute.MINOR_PURCHASE_ALLOWED, required=True, kind=ChannelFieldKind.ENUM, allowed_values=("Y", "N")),
        _text("main_image", "대표이미지", ProductAttribute.MAIN_IMAGE, required=True, kind=ChannelFieldKind.IMAGE, note="대표 1장 + 추가 최대 9장"),
        _text("extra_images", "추가이미지", ProductAttribute.EXTRA_IMAGES, kind=ChannelFieldKind.IMAGE),
        _text("detail_html", "상세설명", ProductAttribute.DETAIL_HTML, kind=ChannelFieldKind.HTML),
        _text("product_summary", "상품 주요정보 요약", ProductAttribute.PRODUCT_SUMMARY, max_chars=500),
        _text("search_keywords", "검색어", ProductAttribute.SEARCH_KEYWORDS, kind=ChannelFieldKind.KEYWORD_LIST, note="최대 20개, 콤마 구분"),
        _text("category_notice", "상품정보제공고시", None, kind=ChannelFieldKind.TEXT, note="카테고리별 고시 항목, 선택 필수"),
        _text("shipping_fee_type", "배송비 유형", ProductAttribute.SHIPPING_FEE_TYPE, required=True, kind=ChannelFieldKind.ENUM, allowed_values=("무료배송", "유료배송", "차등배송비")),
        _text("shipping_fee", "배송비", ProductAttribute.SHIPPING_FEE, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("delivery_days", "발송예정일자", ProductAttribute.DELIVERY_DAYS, kind=ChannelFieldKind.INT, minimum=Decimal("0"), note="당일출고는 1"),
        _text("return_policy", "반품/교환 정책", ProductAttribute.RETURN_POLICY),
    ),
    image_policy=ChannelImagePolicy(
        min_pixels=100,
        recommended_pixels=500,
        max_images=10,
        max_bytes=5 * 1024 * 1024,
        allowed_extensions=(".jpg", ".jpeg", ".png"),
        square_required=False,
        note="대표이미지 1장 + 추가이미지 최대 9장",
    ),
    option_policy=ChannelOptionPolicy(
        max_option_axes=3,
        max_option_values_per_axis=200,
        max_combinations=200,
        option_name_max_chars=50,
        option_value_max_chars=200,
        note="옵션 3개까지, 옵션 기준 200개",
    ),
    source_urls=(
        "https://developers.coupang.com/ko/api/products/product-creation",
        "https://marketplace.coupang.com/register",
        "https://marketplace.coupang.com/mba/listing",
        "https://marketplace.coupang.com/information-center/marketplace3p-product-info-update-uid",
    ),
    source_checked_on=PILOT_SOURCE_CHECKED_ON,
)


NAVER_SMART_STORE_PROFILE = ChannelProfile(
    channel_id=NAVER_SMART_STORE,
    display_name="네이버 스마트스토어",
    admin_surface="스마트스토어 관리자 > 상품관리 > 상품등록",
    fields=(
        _text("product_name", "상품명", ProductAttribute.PRODUCT_NAME, required=True, max_chars=100),
        _text("category_path", "카테고리", ProductAttribute.CATEGORY_PATH, required=True, note="대/중/소 3단계"),
        _text("brand", "브랜드", ProductAttribute.BRAND, required=True, note="네이버쇼핑 브랜드 등록 필요"),
        _text("manufacturer", "제조사", ProductAttribute.MANUFACTURER),
        _text("origin", "원산지", ProductAttribute.ORIGIN),
        _text("model_name", "모델명/품번", ProductAttribute.MODEL_NAME, required=True),
        _text("sale_price", "판매가", ProductAttribute.SALE_PRICE, required=True, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("list_price", "정가", ProductAttribute.LIST_PRICE, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("stock_quantity", "재고수량", ProductAttribute.STOCK_QUANTITY, required=True, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("min_order_quantity", "최소 구매 수량", ProductAttribute.MIN_ORDER_QUANTITY, kind=ChannelFieldKind.INT, minimum=Decimal("1")),
        _text("unit", "단위", ProductAttribute.UNIT),
        _text("product_summary", "상품 간략 정보", ProductAttribute.PRODUCT_SUMMARY, max_chars=500),
        _text("detail_html", "상품 상세설명", ProductAttribute.DETAIL_HTML, kind=ChannelFieldKind.HTML),
        _text("main_image", "대표이미지", ProductAttribute.MAIN_IMAGE, required=True, kind=ChannelFieldKind.IMAGE, note="권장 1000x1000, 20MB 이하"),
        _text("extra_images", "추가이미지", ProductAttribute.EXTRA_IMAGES, kind=ChannelFieldKind.IMAGE),
        _text("search_keywords", "검색어/태그", ProductAttribute.SEARCH_KEYWORDS, kind=ChannelFieldKind.KEYWORD_LIST),
        _text("shipping_fee_type", "배송비", ProductAttribute.SHIPPING_FEE_TYPE, required=True, kind=ChannelFieldKind.ENUM, allowed_values=("무료배송", "유료배송", "차등배송비")),
        _text("shipping_fee", "배송비 금액", ProductAttribute.SHIPPING_FEE, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("delivery_days", "발송예정일", ProductAttribute.DELIVERY_DAYS, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("return_policy", "반품/교환 안내", ProductAttribute.RETURN_POLICY),
        _text("weight_kg", "무게", ProductAttribute.WEIGHT_KG, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("width_mm", "가로", ProductAttribute.WIDTH_MM, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("height_mm", "세로", ProductAttribute.HEIGHT_MM, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("depth_mm", "높이", ProductAttribute.DEPTH_MM, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
    ),
    image_policy=ChannelImagePolicy(
        min_pixels=300,
        recommended_pixels=1000,
        max_images=20,
        max_bytes=20 * 1024 * 1024,
        allowed_extensions=(".jpg", ".jpeg", ".png", ".gif", ".bmp"),
        square_required=False,
        note="권장 1000x1000, 쇼핑 연동은 300px 초과와 4000px 미만 필요",
    ),
    option_policy=ChannelOptionPolicy(
        max_option_axes=5,
        max_option_values_per_axis=100,
        max_combinations=1000,
        option_name_max_chars=50,
        option_value_max_chars=100,
        note="조합형/독립형 선택, SKU 재고 연동",
    ),
    source_urls=(
        "https://help.sell.smartstore.naver.com/faq/content.help?faqId=4188",
        "https://help.sell.smartstore.naver.com/faq/content.help?faqId=3378",
        "https://help.sell.smartstore.naver.com/faq/content.help?faqId=14747",
    ),
    source_checked_on=PILOT_SOURCE_CHECKED_ON,
)


ELEVENST_PROFILE = ChannelProfile(
    channel_id=ELEVENST,
    display_name="11번가 셀러오피스",
    admin_surface="셀러오피스 > 상품관리 > 상품등록",
    fields=(
        _text("product_name", "상품명", ProductAttribute.PRODUCT_NAME, required=True, max_chars=100, note="브랜드는 상품명이 아니라 브랜드 항목에 입력"),
        _text("category_path", "카테고리", ProductAttribute.CATEGORY_PATH, required=True),
        _text("brand", "브랜드", ProductAttribute.BRAND, required=True),
        _text("model_name", "모델명/품번", ProductAttribute.MODEL_NAME),
        _text("sale_price", "판매가", ProductAttribute.SALE_PRICE, required=True, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("stock_quantity", "재고수량", ProductAttribute.STOCK_QUANTITY, required=True, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("min_order_quantity", "최소 구매 수량", ProductAttribute.MIN_ORDER_QUANTITY, kind=ChannelFieldKind.INT, minimum=Decimal("1")),
        _text("main_image", "대표이미지", ProductAttribute.MAIN_IMAGE, required=True, kind=ChannelFieldKind.IMAGE, note="600x600 이상, 1000x1000 권장"),
        _text("extra_images", "추가이미지", ProductAttribute.EXTRA_IMAGES, kind=ChannelFieldKind.IMAGE),
        _text("detail_html", "추가상세정보", ProductAttribute.DETAIL_HTML, kind=ChannelFieldKind.HTML, note="이미지 alt 대체텍스트 필수"),
        _text("search_keywords", "검색어", ProductAttribute.SEARCH_KEYWORDS, kind=ChannelFieldKind.KEYWORD_LIST),
        _text("shipping_fee_type", "배송비", ProductAttribute.SHIPPING_FEE_TYPE, required=True, kind=ChannelFieldKind.ENUM, allowed_values=("무료배송", "유료배송", "차등배송비")),
        _text("shipping_fee", "배송비 금액", ProductAttribute.SHIPPING_FEE, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("delivery_days", "발송예정일", ProductAttribute.DELIVERY_DAYS, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("return_policy", "반품/교환 정책", ProductAttribute.RETURN_POLICY),
        _text("warranty", "보증기간/AS", ProductAttribute.WARRANTY),
    ),
    image_policy=ChannelImagePolicy(
        min_pixels=600,
        recommended_pixels=1000,
        max_images=5,
        max_bytes=10 * 1024 * 1024,
        allowed_extensions=(".jpg", ".jpeg", ".png", ".gif"),
        square_required=True,
        note="600x600 이상, 이미지 내 텍스트·워터마크 제한 있음",
    ),
    option_policy=ChannelOptionPolicy(
        max_option_axes=3,
        max_option_values_per_axis=100,
        max_combinations=1000,
        option_name_max_chars=40,
        option_value_max_chars=50,
        note="조합형 옵션 3개, 옵션명당 옵션값 100개",
    ),
    source_urls=(
        "http://www.11st.co.kr/tpost/FrontTPostAction.tmall?NtceNo=856123&method=getNoticeView&type=so",
        "http://11st.co.kr/tpost/FrontTPostAction.tmall?brdInfoNo=65981072&method=getTPostBoard&sellGroupCode=CM024&unityBrdNo=43",
        "https://i.011st.com/ui_img/seller/pdf/prod.pdf",
    ),
    source_checked_on=PILOT_SOURCE_CHECKED_ON,
)


OWN_MALL_PROFILE = ChannelProfile(
    channel_id=OWN_MALL,
    display_name="자체몰(카페24 콘솔 기준)",
    admin_surface="카페24 부운영자 > 상품 > 상품등록 > 일반등록",
    fields=(
        _text("product_name", "상품명", ProductAttribute.PRODUCT_NAME, required=True, max_chars=200),
        _text("category_path", "상품분류", ProductAttribute.CATEGORY_PATH, required=True),
        _text("brand", "브랜드", ProductAttribute.BRAND),
        _text("sale_price", "판매가", ProductAttribute.SALE_PRICE, required=True, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("list_price", "소비자가", ProductAttribute.LIST_PRICE, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("stock_quantity", "재고수량", ProductAttribute.STOCK_QUANTITY, required=True, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("min_order_quantity", "최소 구매 수량", ProductAttribute.MIN_ORDER_QUANTITY, kind=ChannelFieldKind.INT, minimum=Decimal("1")),
        _text("unit", "단위", ProductAttribute.UNIT),
        _text("main_image", "대표이미지", ProductAttribute.MAIN_IMAGE, required=True, kind=ChannelFieldKind.IMAGE),
        _text("extra_images", "추가이미지", ProductAttribute.EXTRA_IMAGES, kind=ChannelFieldKind.IMAGE),
        _text("detail_html", "상품 상세설명", ProductAttribute.DETAIL_HTML, kind=ChannelFieldKind.HTML),
        _text("product_summary", "상품 요약", ProductAttribute.PRODUCT_SUMMARY, max_chars=500),
        _text("shipping_fee_type", "배송비", ProductAttribute.SHIPPING_FEE_TYPE, kind=ChannelFieldKind.ENUM, allowed_values=("무료배송", "유료배송", "차등배송비")),
        _text("shipping_fee", "배송비 금액", ProductAttribute.SHIPPING_FEE, kind=ChannelFieldKind.DECIMAL, minimum=Decimal("0")),
        _text("delivery_days", "발송예정일", ProductAttribute.DELIVERY_DAYS, kind=ChannelFieldKind.INT, minimum=Decimal("0")),
        _text("return_policy", "반품/교환 정책", ProductAttribute.RETURN_POLICY),
        _text("warranty", "AS 안내", ProductAttribute.WARRANTY),
    ),
    image_policy=ChannelImagePolicy(
        min_pixels=300,
        recommended_pixels=1000,
        max_images=10,
        max_bytes=10 * 1024 * 1024,
        allowed_extensions=(".jpg", ".jpeg", ".png", ".gif"),
        square_required=False,
        note="자체몰 기준, 플랫폼별 정책 차이 있음",
    ),
    option_policy=ChannelOptionPolicy(
        max_option_axes=5,
        max_option_values_per_axis=100,
        max_combinations=1000,
        option_name_max_chars=50,
        option_value_max_chars=100,
        note="조합/분리/직접입력 조합형 지원",
    ),
    source_urls=(
        "https://antigravity.notion.site/24-8e596f8b4f2e41a986e765df8143cca3",
    ),
    source_checked_on=PILOT_SOURCE_CHECKED_ON,
)


CHANNEL_PROFILES: tuple[ChannelProfile, ...] = (
    COUPANG_PROFILE,
    NAVER_SMART_STORE_PROFILE,
    ELEVENST_PROFILE,
    OWN_MALL_PROFILE,
)


def channel_profile(channel_id: str) -> ChannelProfile:
    for profile in CHANNEL_PROFILES:
        if profile.channel_id == channel_id:
            return profile
    raise KeyError(channel_id)


__all__ = [
    "CHANNEL_PROFILES",
    "COUPANG",
    "COUPANG_PROFILE",
    "ELEVENST",
    "ELEVENST_PROFILE",
    "NAVER_SMART_STORE",
    "NAVER_SMART_STORE_PROFILE",
    "OWN_MALL",
    "OWN_MALL_PROFILE",
    "PILOT_SOURCE_CHECKED_ON",
    "channel_profile",
]
