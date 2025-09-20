from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CartItem(_message.Message):
    __slots__ = ("product_id", "quantity")
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    quantity: int
    def __init__(self, product_id: _Optional[str] = ..., quantity: _Optional[int] = ...) -> None: ...

class AddItemRequest(_message.Message):
    __slots__ = ("user_id", "item")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ITEM_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    item: CartItem
    def __init__(self, user_id: _Optional[str] = ..., item: _Optional[_Union[CartItem, _Mapping]] = ...) -> None: ...

class EmptyCartRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class GetCartRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class Cart(_message.Message):
    __slots__ = ("user_id", "items")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    items: _containers.RepeatedCompositeFieldContainer[CartItem]
    def __init__(self, user_id: _Optional[str] = ..., items: _Optional[_Iterable[_Union[CartItem, _Mapping]]] = ...) -> None: ...

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListRecommendationsRequest(_message.Message):
    __slots__ = ("user_id", "product_ids")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_IDS_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    product_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, user_id: _Optional[str] = ..., product_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class ListRecommendationsResponse(_message.Message):
    __slots__ = ("product_ids",)
    PRODUCT_IDS_FIELD_NUMBER: _ClassVar[int]
    product_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, product_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class Product(_message.Message):
    __slots__ = ("id", "name", "description", "picture", "price_usd", "categories")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PICTURE_FIELD_NUMBER: _ClassVar[int]
    PRICE_USD_FIELD_NUMBER: _ClassVar[int]
    CATEGORIES_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    description: str
    picture: str
    price_usd: Money
    categories: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., picture: _Optional[str] = ..., price_usd: _Optional[_Union[Money, _Mapping]] = ..., categories: _Optional[_Iterable[str]] = ...) -> None: ...

class ListProductsResponse(_message.Message):
    __slots__ = ("products",)
    PRODUCTS_FIELD_NUMBER: _ClassVar[int]
    products: _containers.RepeatedCompositeFieldContainer[Product]
    def __init__(self, products: _Optional[_Iterable[_Union[Product, _Mapping]]] = ...) -> None: ...

class GetProductRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class SearchProductsRequest(_message.Message):
    __slots__ = ("query",)
    QUERY_FIELD_NUMBER: _ClassVar[int]
    query: str
    def __init__(self, query: _Optional[str] = ...) -> None: ...

class SearchProductsResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[Product]
    def __init__(self, results: _Optional[_Iterable[_Union[Product, _Mapping]]] = ...) -> None: ...

class GetQuoteRequest(_message.Message):
    __slots__ = ("address", "items")
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    address: Address
    items: _containers.RepeatedCompositeFieldContainer[CartItem]
    def __init__(self, address: _Optional[_Union[Address, _Mapping]] = ..., items: _Optional[_Iterable[_Union[CartItem, _Mapping]]] = ...) -> None: ...

class GetQuoteResponse(_message.Message):
    __slots__ = ("cost_usd",)
    COST_USD_FIELD_NUMBER: _ClassVar[int]
    cost_usd: Money
    def __init__(self, cost_usd: _Optional[_Union[Money, _Mapping]] = ...) -> None: ...

class ShipOrderRequest(_message.Message):
    __slots__ = ("address", "items")
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    address: Address
    items: _containers.RepeatedCompositeFieldContainer[CartItem]
    def __init__(self, address: _Optional[_Union[Address, _Mapping]] = ..., items: _Optional[_Iterable[_Union[CartItem, _Mapping]]] = ...) -> None: ...

class ShipOrderResponse(_message.Message):
    __slots__ = ("tracking_id",)
    TRACKING_ID_FIELD_NUMBER: _ClassVar[int]
    tracking_id: str
    def __init__(self, tracking_id: _Optional[str] = ...) -> None: ...

class Address(_message.Message):
    __slots__ = ("street_address", "city", "state", "country", "zip_code")
    STREET_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    CITY_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    COUNTRY_FIELD_NUMBER: _ClassVar[int]
    ZIP_CODE_FIELD_NUMBER: _ClassVar[int]
    street_address: str
    city: str
    state: str
    country: str
    zip_code: int
    def __init__(self, street_address: _Optional[str] = ..., city: _Optional[str] = ..., state: _Optional[str] = ..., country: _Optional[str] = ..., zip_code: _Optional[int] = ...) -> None: ...

class Money(_message.Message):
    __slots__ = ("currency_code", "units", "nanos")
    CURRENCY_CODE_FIELD_NUMBER: _ClassVar[int]
    UNITS_FIELD_NUMBER: _ClassVar[int]
    NANOS_FIELD_NUMBER: _ClassVar[int]
    currency_code: str
    units: int
    nanos: int
    def __init__(self, currency_code: _Optional[str] = ..., units: _Optional[int] = ..., nanos: _Optional[int] = ...) -> None: ...

class GetSupportedCurrenciesResponse(_message.Message):
    __slots__ = ("currency_codes",)
    CURRENCY_CODES_FIELD_NUMBER: _ClassVar[int]
    currency_codes: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, currency_codes: _Optional[_Iterable[str]] = ...) -> None: ...

class CurrencyConversionRequest(_message.Message):
    __slots__ = ("to_code",)
    FROM_FIELD_NUMBER: _ClassVar[int]
    TO_CODE_FIELD_NUMBER: _ClassVar[int]
    to_code: str
    def __init__(self, to_code: _Optional[str] = ..., **kwargs) -> None: ...

class CreditCardInfo(_message.Message):
    __slots__ = ("credit_card_number", "credit_card_cvv", "credit_card_expiration_year", "credit_card_expiration_month")
    CREDIT_CARD_NUMBER_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_CVV_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_EXPIRATION_YEAR_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_EXPIRATION_MONTH_FIELD_NUMBER: _ClassVar[int]
    credit_card_number: str
    credit_card_cvv: int
    credit_card_expiration_year: int
    credit_card_expiration_month: int
    def __init__(self, credit_card_number: _Optional[str] = ..., credit_card_cvv: _Optional[int] = ..., credit_card_expiration_year: _Optional[int] = ..., credit_card_expiration_month: _Optional[int] = ...) -> None: ...

class ChargeRequest(_message.Message):
    __slots__ = ("amount", "credit_card")
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    amount: Money
    credit_card: CreditCardInfo
    def __init__(self, amount: _Optional[_Union[Money, _Mapping]] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ...) -> None: ...

class ChargeResponse(_message.Message):
    __slots__ = ("transaction_id",)
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    transaction_id: str
    def __init__(self, transaction_id: _Optional[str] = ...) -> None: ...

class OrderItem(_message.Message):
    __slots__ = ("item", "cost")
    ITEM_FIELD_NUMBER: _ClassVar[int]
    COST_FIELD_NUMBER: _ClassVar[int]
    item: CartItem
    cost: Money
    def __init__(self, item: _Optional[_Union[CartItem, _Mapping]] = ..., cost: _Optional[_Union[Money, _Mapping]] = ...) -> None: ...

class OrderResult(_message.Message):
    __slots__ = ("order_id", "shipping_tracking_id", "shipping_cost", "shipping_address", "items")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    SHIPPING_TRACKING_ID_FIELD_NUMBER: _ClassVar[int]
    SHIPPING_COST_FIELD_NUMBER: _ClassVar[int]
    SHIPPING_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    shipping_tracking_id: str
    shipping_cost: Money
    shipping_address: Address
    items: _containers.RepeatedCompositeFieldContainer[OrderItem]
    def __init__(self, order_id: _Optional[str] = ..., shipping_tracking_id: _Optional[str] = ..., shipping_cost: _Optional[_Union[Money, _Mapping]] = ..., shipping_address: _Optional[_Union[Address, _Mapping]] = ..., items: _Optional[_Iterable[_Union[OrderItem, _Mapping]]] = ...) -> None: ...

class SendOrderConfirmationRequest(_message.Message):
    __slots__ = ("email", "order")
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    ORDER_FIELD_NUMBER: _ClassVar[int]
    email: str
    order: OrderResult
    def __init__(self, email: _Optional[str] = ..., order: _Optional[_Union[OrderResult, _Mapping]] = ...) -> None: ...

class PlaceOrderRequest(_message.Message):
    __slots__ = ("user_id", "user_currency", "address", "email", "credit_card")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    USER_CURRENCY_FIELD_NUMBER: _ClassVar[int]
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    CREDIT_CARD_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    user_currency: str
    address: Address
    email: str
    credit_card: CreditCardInfo
    def __init__(self, user_id: _Optional[str] = ..., user_currency: _Optional[str] = ..., address: _Optional[_Union[Address, _Mapping]] = ..., email: _Optional[str] = ..., credit_card: _Optional[_Union[CreditCardInfo, _Mapping]] = ...) -> None: ...

class PlaceOrderResponse(_message.Message):
    __slots__ = ("order",)
    ORDER_FIELD_NUMBER: _ClassVar[int]
    order: OrderResult
    def __init__(self, order: _Optional[_Union[OrderResult, _Mapping]] = ...) -> None: ...

class AdRequest(_message.Message):
    __slots__ = ("context_keys",)
    CONTEXT_KEYS_FIELD_NUMBER: _ClassVar[int]
    context_keys: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, context_keys: _Optional[_Iterable[str]] = ...) -> None: ...

class AdResponse(_message.Message):
    __slots__ = ("ads",)
    ADS_FIELD_NUMBER: _ClassVar[int]
    ads: _containers.RepeatedCompositeFieldContainer[Ad]
    def __init__(self, ads: _Optional[_Iterable[_Union[Ad, _Mapping]]] = ...) -> None: ...

class Ad(_message.Message):
    __slots__ = ("redirect_url", "text")
    REDIRECT_URL_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    redirect_url: str
    text: str
    def __init__(self, redirect_url: _Optional[str] = ..., text: _Optional[str] = ...) -> None: ...
