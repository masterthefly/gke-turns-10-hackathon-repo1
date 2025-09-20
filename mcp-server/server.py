import grpc
import json
import logging
from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google.protobuf.json_format import MessageToDict

# Generated gRPC stubs - need to run protoc to get these
try:
    import demo_pb2
    import demo_pb2_grpc
except ImportError:
    print("Can't find the gRPC stubs. Did you run protoc?")
    exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Service addresses inside the cluster
PRODUCT_CATALOG_SERVICE_ADDR = 'productcatalogservice.default.svc.cluster.local:3550'
CART_SERVICE_ADDR = 'cartservice.default.svc.cluster.local:7070'

app = FastAPI(title="Online Boutique MCP Server", version="1.0.0")

# request models
class SearchRequest(BaseModel):
    query: str

class ProductRequest(BaseModel):
    product_id: str

class AddToCartRequest(BaseModel):
    user_id: str
    product_id: str
    quantity: int

class CartRequest(BaseModel):
    user_id: str

class EmptyCartRequest(BaseModel):
    user_id: str

class RemoveFromCartRequest(BaseModel):
    user_id: str
    product_id: str

def clean_search_query(query: str) -> str:
    """Clean and simplify search query by extracting key meaningful terms"""
    import re

    # Convert to lowercase
    query = query.lower().strip()

    # Extract key product/intent terms
    key_terms = []

    # Common product categories
    product_categories = {
        'cooking': ['cook', 'cooking', 'kitchen', 'chef', 'culinary'],
        'clothing': ['shirt', 'pants', 'dress', 'jacket', 'shoes', 'clothing'],
        'accessories': ['watch', 'jewelry', 'bag', 'wallet', 'accessories'],
        'electronics': ['phone', 'laptop', 'computer', 'electronics'],
        'home': ['home', 'house', 'decor', 'furniture'],
        'gifts': ['gift', 'present']
    }

    # Find category matches
    found_categories = []
    for category, terms in product_categories.items():
        if any(term in query for term in terms):
            found_categories.append(category)
            key_terms.extend([term for term in terms if term in query])

    # Extract other meaningful words (3+ characters, not common words)
    stop_words = {'the', 'for', 'and', 'with', 'someone', 'who', 'loves', 'that', 'this', 'has', 'are', 'was', 'will', 'can', 'could', 'would', 'should'}
    words = re.findall(r'\b\w{3,}\b', query)
    meaningful_words = [word for word in words if word not in stop_words]

    # If we found specific categories, focus on those
    if found_categories:
        if 'cooking' in found_categories or 'gifts' in found_categories:
            # For cooking gifts, focus on kitchen-related terms
            kitchen_terms = ['kitchen', 'cook', 'cooking', 'chef', 'culinary', 'utensils', 'cookware']
            result_terms = [term for term in kitchen_terms if term in query]
            if not result_terms:
                result_terms = ['kitchen']  # Default fallback for cooking
        else:
            result_terms = list(set(key_terms))[:3]
    else:
        # Use first few meaningful words
        result_terms = meaningful_words[:3]

    cleaned = ' '.join(result_terms) if result_terms else query

    # If cleaning resulted in empty string, return first meaningful word or original
    if not cleaned.strip():
        cleaned = meaningful_words[0] if meaningful_words else query

    return cleaned

def get_user_friendly_error_message(error_message: str, operation: str) -> str:
    """Convert gRPC and technical errors to user-friendly messages"""
    error_lower = str(error_message).lower()
    
    if "no product with id" in error_lower or "not found" in error_lower:
        return "The requested product is not available or may have been discontinued."
    elif "timeout" in error_lower or "deadline" in error_lower:
        return "The request is taking too long. Please try again."
    elif "connection" in error_lower or "unavailable" in error_lower:
        return "Our services are temporarily unavailable. Please try again in a moment."
    elif "invalid" in error_lower or "bad request" in error_lower:
        return "There was an issue with the request. Please check your input and try again."
    elif "permission" in error_lower or "denied" in error_lower:
        return "Access denied. Please check your permissions."
    else:
        if operation == "search":
            return "Unable to search for products right now. Please try again."
        elif operation == "cart":
            return "Unable to update your cart right now. Please try again."
        elif operation == "product":
            return "Unable to load product information right now. Please try again."
        else:
            return "Something went wrong. Please try again."

def enhanced_fuzzy_match_products(query, products, threshold=0.4):
    """Enhanced fuzzy matching with plural/singular handling and better word matching"""
    from difflib import SequenceMatcher
    import re
    
    query_lower = query.lower().strip()
    matched_products = []
    
    # Handle plurals - convert search terms to both singular and plural forms
    query_variants = [query_lower]
    
    # Simple plural/singular conversion
    if query_lower.endswith('s') and len(query_lower) > 3:
        # Try removing 's' for singular
        singular = query_lower.rstrip('s')
        query_variants.append(singular)
        # Also try removing 'es'
        if query_lower.endswith('es') and len(query_lower) > 4:
            singular_es = query_lower[:-2]
            query_variants.append(singular_es)
    else:
        # Try adding 's' for plural
        query_variants.append(query_lower + 's')
        # Try adding 'es' for plural
        query_variants.append(query_lower + 'es')
    
    # Split query into words for better matching
    query_words = []
    for variant in query_variants:
        query_words.extend(variant.split())
    query_words = list(set(query_words))  # Remove duplicates
    
    for product in products:
        name_lower = product.get('name', '').lower()
        desc_lower = product.get('description', '').lower()
        categories_lower = ' '.join(product.get('categories', [])).lower()
        
        # Combine all searchable text
        searchable_text = f"{name_lower} {desc_lower} {categories_lower}"
        
        max_similarity = 0
        
        # Method 1: Direct string similarity for each query variant
        for variant in query_variants:
            name_sim = SequenceMatcher(None, variant, name_lower).ratio()
            desc_sim = SequenceMatcher(None, variant, desc_lower).ratio()
            cat_sim = SequenceMatcher(None, variant, categories_lower).ratio()
            max_similarity = max(max_similarity, name_sim, desc_sim, cat_sim)
        
        # Method 2: Word-based matching
        word_score = 0
        total_words = len(query_words)
        
        if total_words > 0:
            matches = 0
            for q_word in query_words:
                if len(q_word) >= 3:  # Only count substantial words
                    # Check for exact word matches
                    if q_word in searchable_text:
                        matches += 1
                    # Check for partial matches within words
                    elif any(q_word in word for word in searchable_text.split() if len(word) >= 3):
                        matches += 0.7
                    # Check for substring matches
                    elif any(word in q_word for word in searchable_text.split() if len(word) >= 3):
                        matches += 0.5
            
            word_score = matches / total_words
        
        # Method 3: Category matching (exact or partial)
        category_score = 0
        for category in product.get('categories', []):
            for variant in query_variants:
                if variant in category.lower() or category.lower() in variant:
                    category_score = 0.8
                    break
        
        # Combine scores with weights
        final_score = max(
            max_similarity,           # Direct similarity
            word_score * 0.9,        # Word matching (high weight)
            category_score           # Category matching
        )
        
        # Boost score if query appears in product name (most important)
        for variant in query_variants:
            if variant in name_lower:
                final_score = max(final_score, 0.8)
        
        if final_score >= threshold:
            product['_similarity'] = final_score
            matched_products.append(product)
    
    # Sort by similarity score (highest first)
    matched_products.sort(key=lambda x: x.get('_similarity', 0), reverse=True)
    
    # Remove the similarity score from final results
    for p in matched_products:
        p.pop('_similarity', None)
    
    return matched_products

def fuzzy_match_products(query, products, threshold=0.6):
    """Filter products by fuzzy matching against name and description - restored original function"""
    from difflib import SequenceMatcher
    
    query_lower = query.lower()
    matched_products = []
    
    for product in products:
        # Check name
        name_lower = product.get('name', '').lower()
        name_similarity = SequenceMatcher(None, query_lower, name_lower).ratio()
        
        # Check description
        desc_lower = product.get('description', '').lower()
        desc_similarity = SequenceMatcher(None, query_lower, desc_lower).ratio()
        
        # Check if query words are in name/description
        query_words = query_lower.split()
        name_words = name_lower.split()
        desc_words = desc_lower.split()
        
        word_matches = 0
        for q_word in query_words:
            if any(q_word in n_word for n_word in name_words):
                word_matches += 1
            elif any(q_word in d_word for d_word in desc_words):
                word_matches += 0.5
        
        word_score = word_matches / len(query_words) if query_words else 0
        
        # Combined score
        max_similarity = max(name_similarity, desc_similarity, word_score)
        
        if max_similarity >= threshold:
            product['_similarity'] = max_similarity
            matched_products.append(product)
    
    # Sort by similarity score
    matched_products.sort(key=lambda x: x.get('_similarity', 0), reverse=True)
    
    # Remove the similarity score from final results
    for p in matched_products:
        p.pop('_similarity', None)
    
    return matched_products

@app.post("/search_products")
async def search_products(request: SearchRequest):
    try:
        # Step 1: Try direct gRPC search first
        results_from_grpc = []
        
        with grpc.insecure_channel(PRODUCT_CATALOG_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
            grpc_request = demo_pb2.SearchProductsRequest(query=request.query)
            response = stub.SearchProducts(grpc_request)
            
            response_dict = MessageToDict(response)
            
            if 'results' in response_dict:
                for product in response_dict['results']:
                    p = {
                        'id': product.get('id', ''),
                        'name': product.get('name', ''),
                        'description': product.get('description', ''),
                        'price': product.get('priceUsd', {}),
                        'categories': product.get('categories', [])
                    }
                    results_from_grpc.append(p)
        
        # Step 2: If gRPC search returns few/no results, fall back to fuzzy search on all products
        if len(results_from_grpc) < 3:  # If we got less than 3 results, enhance with fuzzy search
            logger.info(f"gRPC search returned {len(results_from_grpc)} results for '{request.query}', enhancing with fuzzy search")
            
            # Get all products for fuzzy matching
            with grpc.insecure_channel(PRODUCT_CATALOG_SERVICE_ADDR) as channel:
                stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
                list_request = demo_pb2.Empty()
                list_response = stub.ListProducts(list_request)
                
                list_response_dict = MessageToDict(list_response)
                all_products = []
                
                if 'products' in list_response_dict:
                    for product in list_response_dict['products']:
                        p = {
                            'id': product.get('id', ''),
                            'name': product.get('name', ''),
                            'description': product.get('description', ''),
                            'price': product.get('priceUsd', {}),
                            'categories': product.get('categories', [])
                        }
                        all_products.append(p)
                
                # Clean query for better fuzzy matching - extract key terms
                cleaned_query = clean_search_query(request.query)
                logger.info(f"Cleaned query from '{request.query}' to '{cleaned_query}' for fuzzy search")

                # Enhanced fuzzy matching with plural/singular handling
                fuzzy_results = enhanced_fuzzy_match_products(cleaned_query, all_products, threshold=0.4)
                logger.info(f"Fuzzy search found {len(fuzzy_results)} additional results")
                
                # Combine results, avoiding duplicates
                existing_ids = set(p.get('id', '') for p in results_from_grpc)
                for fuzzy_result in fuzzy_results:
                    if fuzzy_result.get('id', '') not in existing_ids:
                        results_from_grpc.append(fuzzy_result)
                
                # Limit total results
                results_from_grpc = results_from_grpc[:15]
        
        logger.info(f"Final search results: {len(results_from_grpc)} products for query '{request.query}'")
        
        return {
            'status': 'success',
            'query': request.query,
            'results': results_from_grpc,
            'count': len(results_from_grpc)
        }
        
    except grpc.RpcError as e:
        logger.error(f"gRPC error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "search")
        raise HTTPException(status_code=500, detail=user_friendly_message)
    except Exception as e:
        logger.error(f"Error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "search")
        raise HTTPException(status_code=500, detail=user_friendly_message)

@app.post("/get_product_details")
async def get_product_details(request: ProductRequest):
    try:
        with grpc.insecure_channel(PRODUCT_CATALOG_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
            grpc_request = demo_pb2.GetProductRequest(id=request.product_id)
            response = stub.GetProduct(grpc_request)
            
            response_dict = MessageToDict(response)
            
            product = {
                'id': response_dict.get('id', ''),
                'name': response_dict.get('name', ''),
                'description': response_dict.get('description', ''),
                'price': response_dict.get('priceUsd', {}),
                'categories': response_dict.get('categories', []),
                'picture': response_dict.get('picture', '')
            }
            
            return {'status': 'success', 'product': product}
            
    except grpc.RpcError as e:
        logger.error(f"gRPC error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "product")
        raise HTTPException(status_code=500, detail=user_friendly_message)
    except Exception as e:
        logger.error(f"Error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "product")
        raise HTTPException(status_code=500, detail=user_friendly_message)

@app.post("/add_item_to_cart")
async def add_item_to_cart(request: AddToCartRequest):
    # Input validation
    if not request.user_id or not request.user_id.strip():
        return {
            'status': 'error',
            'message': 'User ID is required',
            'user_id': request.user_id,
            'product_id': request.product_id
        }
    
    if not request.product_id or not request.product_id.strip():
        return {
            'status': 'error',
            'message': 'Product ID is required',
            'user_id': request.user_id,
            'product_id': request.product_id
        }
    
    if request.quantity <= 0:
        return {
            'status': 'error',
            'message': 'Quantity must be greater than 0',
            'user_id': request.user_id,
            'product_id': request.product_id
        }
    
    try:
        logger.info(f"Adding item to cart - User: {request.user_id}, Product: {request.product_id}, Quantity: {request.quantity}")
        
        with grpc.insecure_channel(CART_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.CartServiceStub(channel)
            item = demo_pb2.CartItem(product_id=request.product_id, quantity=request.quantity)
            grpc_request = demo_pb2.AddItemRequest(user_id=request.user_id, item=item)
            response = stub.AddItem(grpc_request)
            
            logger.info(f"Successfully added {request.quantity} unit(s) of {request.product_id} to cart for user {request.user_id}")
            
            return {
                'status': 'success',
                'message': f'Added {request.quantity} unit(s) of {request.product_id} to cart',
                'user_id': request.user_id,
                'product_id': request.product_id,
                'quantity': request.quantity
            }
            
    except grpc.RpcError as e:
        logger.error(f"gRPC Cart error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id,
            'product_id': request.product_id
        }
    except Exception as e:
        logger.error(f"Cart error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id,
            'product_id': request.product_id
        }

@app.post("/get_cart_contents")
async def get_cart_contents(request: CartRequest):
    try:
        logger.info(f"Retrieving cart contents for user: {request.user_id}")
        
        with grpc.insecure_channel(CART_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.CartServiceStub(channel)
            grpc_request = demo_pb2.GetCartRequest(user_id=request.user_id)
            response = stub.GetCart(grpc_request)
            
            response_dict = MessageToDict(response)
            items = response_dict.get('items', [])
            
            cart_items = []
            for item in items:
                cart_items.append({
                    'product_id': item.get('productId', ''),
                    'quantity': item.get('quantity', 0)
                })
            
            logger.info(f"Found {len(cart_items)} items in cart for user {request.user_id}")
            
            return {
                'status': 'success',
                'user_id': request.user_id,
                'items': cart_items,
                'item_count': len(cart_items)
            }
            
    except grpc.RpcError as e:
        logger.error(f"gRPC Cart retrieval error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id,
            'items': [],
            'item_count': 0
        }
    except Exception as e:
        logger.error(f"Cart retrieval error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id,
            'items': [],
            'item_count': 0
        }

@app.post("/empty_cart")
async def empty_cart(request: EmptyCartRequest):
    try:
        with grpc.insecure_channel(CART_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.CartServiceStub(channel)
            grpc_request = demo_pb2.EmptyCartRequest(user_id=request.user_id)
            response = stub.EmptyCart(grpc_request)
            
            return {
                'status': 'success',
                'message': f'Cart emptied for {request.user_id}',
                'user_id': request.user_id
            }
            
    except grpc.RpcError as e:
        logger.error(f"gRPC Empty cart error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id
        }
    except Exception as e:
        logger.error(f"Empty cart error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id
        }

@app.post("/remove_item_from_cart")
async def remove_item_from_cart(request: RemoveFromCartRequest):
    # Input validation
    if not request.user_id or not request.user_id.strip():
        return {
            'status': 'error',
            'message': 'User ID is required',
            'user_id': request.user_id,
            'product_id': request.product_id
        }
    
    if not request.product_id or not request.product_id.strip():
        return {
            'status': 'error',
            'message': 'Product ID is required',
            'user_id': request.user_id,
            'product_id': request.product_id
        }
    
    try:
        # First get current cart to find the item
        with grpc.insecure_channel(CART_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.CartServiceStub(channel)
            
            # Get current cart
            get_request = demo_pb2.GetCartRequest(user_id=request.user_id)
            cart_response = stub.GetCart(get_request)
            
            # Find the item to remove
            item_found = False
            for item in cart_response.items:
                if item.product_id == request.product_id:
                    item_found = True
                    break
            
            if not item_found:
                return {
                    'status': 'error',
                    'message': f'Product {request.product_id} not found in cart',
                    'user_id': request.user_id,
                    'product_id': request.product_id
                }
            
            # Empty cart and re-add all items except the one to remove
            empty_request = demo_pb2.EmptyCartRequest(user_id=request.user_id)
            stub.EmptyCart(empty_request)
            
            # Re-add all items except the one being removed
            for item in cart_response.items:
                if item.product_id != request.product_id:
                    add_item = demo_pb2.CartItem(product_id=item.product_id, quantity=item.quantity)
                    add_request = demo_pb2.AddItemRequest(user_id=request.user_id, item=add_item)
                    stub.AddItem(add_request)
            
            return {
                'status': 'success',
                'message': f'Removed {request.product_id} from cart',
                'user_id': request.user_id,
                'product_id': request.product_id
            }
            
    except grpc.RpcError as e:
        logger.error(f"gRPC Remove item error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id,
            'product_id': request.product_id
        }
    except Exception as e:
        logger.error(f"Remove item error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "cart")
        return {
            'status': 'error',
            'message': user_friendly_message,
            'user_id': request.user_id,
            'product_id': request.product_id
        }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mcp-server"}

@app.get("/")
async def root():
    return {
        "service": "Online Boutique MCP Server",
        "version": "1.0.0",
        "status": "running",
        "endpoints": [
            "/search_products",
            "/get_product_details", 
            "/add_item_to_cart",
            "/remove_item_from_cart",
            "/get_cart_contents",
            "/empty_cart",
            "/list_products",
            "/get_product_recommendations",
            "/health",
            "/docs"
        ]
    }

@app.get("/list_products")
async def list_all_products():
    try:
        with grpc.insecure_channel(PRODUCT_CATALOG_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
            # Use Empty() instead of ListProductsRequest()
            grpc_request = demo_pb2.Empty()
            response = stub.ListProducts(grpc_request)
            
            response_dict = MessageToDict(response)
            
            if 'products' in response_dict:
                products = []
                for product in response_dict['products']:
                    products.append({
                        'id': product.get('id', ''),
                        'name': product.get('name', ''),
                        'description': product.get('description', ''),
                        'price': product.get('priceUsd', {}),
                        'categories': product.get('categories', [])
                    })
                
                return {'status': 'success', 'products': products, 'count': len(products)}
            else:
                return {'status': 'success', 'products': [], 'count': 0}
                
    except Exception as e:
        logger.error(f"List products error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "search")
        raise HTTPException(status_code=500, detail=user_friendly_message)

@app.post("/get_product_recommendations")
async def get_product_recommendations(request: SearchRequest):
    """Get product recommendations based on search intent"""
    try:
        # First get all products
        with grpc.insecure_channel(PRODUCT_CATALOG_SERVICE_ADDR) as channel:
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
            grpc_request = demo_pb2.Empty()
            response = stub.ListProducts(grpc_request)
            
            response_dict = MessageToDict(response)
            
            if 'products' in response_dict:
                all_products = []
                for product in response_dict['products']:
                    p = {
                        'id': product.get('id', ''),
                        'name': product.get('name', ''),
                        'description': product.get('description', ''),
                        'price': product.get('priceUsd', {}),
                        'categories': product.get('categories', [])
                    }
                    all_products.append(p)
                
                # Use enhanced fuzzy matching to find relevant products
                matched_products = enhanced_fuzzy_match_products(request.query, all_products, threshold=0.3)
                
                # If no good matches, return top 5 products
                if not matched_products:
                    matched_products = all_products[:5]
                
                return {
                    'status': 'success',
                    'query': request.query,
                    'recommendations': matched_products[:8],  # Return up to 8 recommendations
                    'count': len(matched_products[:8]),
                    'total_available': len(all_products)
                }
            else:
                return {'status': 'success', 'recommendations': [], 'count': 0}
                
    except Exception as e:
        logger.error(f"Recommendations error: {e}")
        user_friendly_message = get_user_friendly_error_message(str(e), "search")
        raise HTTPException(status_code=500, detail=user_friendly_message)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)