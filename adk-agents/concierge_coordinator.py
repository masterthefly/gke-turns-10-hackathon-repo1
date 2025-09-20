import httpx
import json
import logging
import re
import os
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
from functools import lru_cache

# Optional ML imports with graceful fallbacks
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    ML_AVAILABLE = True
except ImportError as e:
    logging.warning(f"ML libraries not available: {e}")
    ML_AVAILABLE = False
    # Create dummy classes/functions for type hints
    class SentenceTransformer:
        pass
    def cosine_similarity(*args):
        return [[0.0]]
    np = None

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    logging.warning("spaCy not available")
    SPACY_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ADK Shopping Concierge", version="2.0.0")

# MCP server URL 
MCP_SERVER_URL = "http://mcp-server-service.default.svc.cluster.local:8080"

# Gemini API key setup
GEMINI_API_KEY = None
try:
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    if not GEMINI_API_KEY:
        try:
            with open('/etc/secrets/gemini-api-key', 'r') as f:
                GEMINI_API_KEY = f.read().strip()
        except FileNotFoundError:
            pass
    if not GEMINI_API_KEY:
        try:
            with open('/var/secrets/gemini-api-key', 'r') as f:
                GEMINI_API_KEY = f.read().strip()
        except FileNotFoundError:
            pass
    if GEMINI_API_KEY:
        logger.info("Gemini API key loaded")
    else:
        logger.warning("No Gemini API key found")
except Exception as e:
    logger.warning(f"Error loading Gemini API key: {e}")

class ChatMessage(BaseModel):
    role: str
    content: str

class ConversationRequest(BaseModel):
    messages: List[ChatMessage]
    user_id: str

class ProductQuery(BaseModel):
    query: str
    user_id: str

class ProductRecommendationRequest(BaseModel):
    user_id: str
    preferences: Optional[List[str]] = []
    budget_max: Optional[float] = None

class CartActionRequest(BaseModel):
    user_id: str
    action: str  
    product_id: Optional[str] = None
    quantity: Optional[int] = 1

class GeminiClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        self.enabled = api_key is not None
        
    async def generate_response(self, prompt: str, temperature: float = 0.7) -> str:
        if not self.enabled:
            return "Gemini AI not available. Using fallback processing."
            
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.base_url,
                    headers={"x-goog-api-key": self.api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": temperature,
                            "maxOutputTokens": 1000
                        }
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Gemini API error: {response.status_code}")
                    return "Sorry, having trouble with AI processing right now."
                
                result = response.json()
                candidates = result.get("candidates", [])
                if candidates and candidates[0].get("content", {}).get("parts"):
                    return candidates[0]["content"]["parts"][0]["text"]
                else:
                    return "Couldn't generate response. Please try again."
                    
        except Exception as e:
            logger.error(f"Gemini API failed: {e}")
            return "AI processing unavailable. Please try again."

def fuzzy_match_products(query, products, threshold=0.6):
    """Filter products by fuzzy matching with improved plural/wildcard handling"""
    from difflib import SequenceMatcher
    
    query_lower = query.lower().strip()
    matched_products = []
    
    # Generate query variants for better matching
    query_variants = [query_lower]
    
    # Handle plurals/singulars
    if query_lower.endswith('s') and len(query_lower) > 3:
        singular = query_lower.rstrip('s')
        query_variants.append(singular)
        if query_lower.endswith('es') and len(query_lower) > 4:
            singular_es = query_lower[:-2]
            query_variants.append(singular_es)
    else:
        query_variants.append(query_lower + 's')
        if not query_lower.endswith('e'):
            query_variants.append(query_lower + 'es')
    
    # Split into words for partial matching
    query_words = []
    for variant in query_variants:
        query_words.extend(variant.split())
    query_words = list(set([w for w in query_words if len(w) > 2]))
    
    for product in products:
        name_lower = product.get('name', '').lower()
        desc_lower = product.get('description', '').lower()
        categories_lower = ' '.join(product.get('categories', [])).lower()
        searchable_text = f"{name_lower} {desc_lower} {categories_lower}"
        
        max_similarity = 0
        
        # Check direct similarity for each variant
        for variant in query_variants:
            name_sim = SequenceMatcher(None, variant, name_lower).ratio()
            desc_sim = SequenceMatcher(None, variant, desc_lower).ratio()
            cat_sim = SequenceMatcher(None, variant, categories_lower).ratio()
            max_similarity = max(max_similarity, name_sim, desc_sim, cat_sim)
        
        # Word-based matching
        if query_words:
            word_matches = 0
            for q_word in query_words:
                if q_word in searchable_text:
                    word_matches += 1
                elif any(q_word in word for word in searchable_text.split() if len(word) > 2):
                    word_matches += 0.7
                elif any(word in q_word for word in searchable_text.split() if len(word) > 2):
                    word_matches += 0.5
            
            word_score = word_matches / len(query_words)
            max_similarity = max(max_similarity, word_score * 0.9)
        
        # Boost for exact matches in product name
        for variant in query_variants:
            if variant in name_lower:
                max_similarity = max(max_similarity, 0.8)
        
        if max_similarity >= threshold:
            product['_similarity'] = max_similarity
            matched_products.append(product)
    
    # Sort by similarity score
    matched_products.sort(key=lambda x: x.get('_similarity', 0), reverse=True)
    
    # Remove the similarity score from final results
    for p in matched_products:
        p.pop('_similarity', None)
    
    return matched_products

class SemanticSearchEngine:
    def __init__(self):
        """Initialize semantic search components with optional ML dependencies"""
        self.model = None
        self.nlp = None
        
        if ML_AVAILABLE:
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Loaded semantic search model")
            except Exception as e:
                logger.warning(f"Failed to load semantic model: {e}")
                self.model = None
        else:
            logger.info("ML libraries not available - semantic search disabled")
        
        if SPACY_AVAILABLE:
            try:
                self.nlp = spacy.load("en_core_web_sm")
                logger.info("Loaded spaCy model")
            except Exception as e:
                logger.warning(f"Failed to load spaCy model: {e}")
                self.nlp = None
        else:
            logger.info("spaCy not available - advanced NLP disabled")
        
        # Cache for product embeddings
        self.product_embeddings_cache = {}
        self.products_cache = []
        self.cache_timestamp = 0
        
        # Intent patterns for classification
        self.intent_patterns = {
            'search': [
                'find', 'search', 'look for', 'show me', 'get me', 'i need', 'i want',
                'looking for', 'searching for', 'where can i find', 'do you have'
            ],
            'cart_view': [
                'cart', 'basket', 'my items', 'what do i have', 'show cart',
                'view cart', 'check cart', 'my bag'
            ],
            'cart_add': [
                'add to cart', 'buy', 'purchase', 'get this', 'i\'ll take',
                'put in cart', 'add this', 'buy this'
            ],
            'recommendations': [
                'recommend', 'suggest', 'what should i buy', 'surprise me',
                'what\'s good', 'what\'s popular', 'best sellers', 'top rated'
            ],
            'help': [
                'help', 'what can you do', 'how does this work', 'instructions',
                'commands', 'options', 'what are my choices'
            ]
        }
    
    def preprocess_text(self, text: str) -> str:
        """Clean and preprocess text"""
        if not text:
            return ""
        
        text = text.lower().strip()
        text = re.sub(r'\s+', ' ', text)
        
        # Simple stop word removal
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        words = text.split()
        words = [w for w in words if w not in stop_words or len(words) <= 3]
        
        return ' '.join(words)
    
    def extract_product_keywords(self, text: str) -> List[str]:
        """Extract product-related keywords from text"""
        product_keywords = {
            'shoes': ['shoes', 'sneakers', 'boots', 'sandals', 'loafers', 'heels', 'flats', 'dress shoes', 'running shoes'],
            'clothing': ['shirt', 'pants', 'dress', 'jacket', 'coat', 'sweater', 'jeans', 'blouse', 'skirt', 'shorts'],
            'accessories': ['watch', 'jewelry', 'necklace', 'bracelet', 'earrings', 'ring', 'bag', 'purse', 'wallet'],
            'electronics': ['phone', 'laptop', 'computer', 'tablet', 'headphones', 'speaker', 'camera', 'tv'],
            'home': ['furniture', 'chair', 'table', 'lamp', 'pillow', 'blanket', 'curtains'],
            'kitchen': ['cookware', 'dishes', 'utensils', 'appliances', 'coffee maker', 'blender'],
            'sports': ['equipment', 'gear', 'fitness', 'exercise', 'weights', 'yoga mat'],
            'books': ['book', 'novel', 'textbook', 'magazine', 'journal']
        }
        
        text_lower = text.lower()
        found_keywords = []
        
        for category, keywords in product_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    found_keywords.append(keyword)
        
        return found_keywords
    
    def extract_context_modifiers(self, text: str) -> List[str]:
        """Extract context that modifies product search"""
        context_map = {
            'meeting': ['formal', 'business', 'professional'],
            'work': ['business', 'professional', 'office'],
            'office': ['business', 'professional', 'formal'],
            'business': ['formal', 'professional'],
            'interview': ['formal', 'professional', 'business'],
            'presentation': ['formal', 'professional', 'business'],
            'casual': ['casual', 'everyday', 'comfortable'],
            'weekend': ['casual', 'relaxed'],
            'home': ['casual', 'comfortable'],
            'running': ['athletic', 'sports', 'fitness'],
            'gym': ['athletic', 'sports', 'fitness'],
            'exercise': ['athletic', 'sports', 'fitness'],
            'workout': ['athletic', 'sports', 'fitness'],
            'summer': ['light', 'breathable', 'cool'],
            'winter': ['warm', 'insulated', 'heavy'],
            'rain': ['waterproof', 'rain'],
            'cold': ['warm', 'insulated']
        }
        
        text_lower = text.lower()
        modifiers = []
        
        for trigger, contexts in context_map.items():
            if trigger in text_lower:
                modifiers.extend(contexts)
        
        return list(set(modifiers))
    
    def extract_entities(self, text: str) -> Dict[str, Any]:
        """Extract entities - basic version without spaCy, advanced version with spaCy"""
        entities = {
            'product_types': [],
            'brands': [],
            'colors': [],
            'materials': [],
            'sizes': [],
            'price_range': None
        }
        
        text_lower = text.lower()
        
        # Extract colors
        colors = ['red', 'blue', 'green', 'black', 'white', 'yellow', 'orange', 'purple', 'pink', 'brown', 'gray', 'grey']
        for color in colors:
            if color in text_lower:
                entities['colors'].append(color)
        
        # Extract sizes
        sizes = ['small', 'medium', 'large', 'xs', 'xl', 'xxl', 's', 'm', 'l']
        for size in sizes:
            if f' {size} ' in f' {text_lower} ' or f' {size}s ' in f' {text_lower} ':
                entities['sizes'].append(size)
        
        # Extract price patterns
        price_pattern = r'\$(\d+(?:\.\d{2})?)'
        price_matches = re.findall(price_pattern, text)
        if price_matches:
            entities['price_range'] = [float(p) for p in price_matches]
        
        # Advanced spaCy extraction if available
        if self.nlp:
            try:
                doc = self.nlp(text)
                for ent in doc.ents:
                    if ent.label_ in ['ORG', 'PRODUCT']:
                        entities['brands'].append(ent.text.lower())
            except Exception as e:
                logger.warning(f"spaCy entity extraction failed: {e}")
        
        return entities
    
    def classify_intent(self, text: str) -> str:
        """Classify user intent - keyword matching enhanced with ML if available"""
        text_lower = text.lower()
        
        # Basic keyword matching
        for intent, patterns in self.intent_patterns.items():
            if any(pattern in text_lower for pattern in patterns):
                return intent
        
        # Advanced semantic classification if ML available
        if self.model and ML_AVAILABLE:
            try:
                query_embedding = self.model.encode([text])
                best_intent = 'search'
                best_score = 0
                
                for intent, patterns in self.intent_patterns.items():
                    pattern_embeddings = self.model.encode(patterns)
                    similarities = cosine_similarity(query_embedding, pattern_embeddings)
                    max_similarity = np.max(similarities)
                    
                    if max_similarity > best_score:
                        best_score = max_similarity
                        best_intent = intent
                
                if best_score > 0.3:
                    return best_intent
            except Exception as e:
                logger.warning(f"Semantic intent classification failed: {e}")
        
        return 'search'
    
    async def enhance_search_query(self, original_query: str, products: List[Dict]) -> str:
        """Enhance search query - preprocessing + semantic enhancement if ML available"""
        processed_query = self.preprocess_text(original_query)
        
        if self.model and ML_AVAILABLE and products:
            try:
                entities = self.extract_entities(original_query)
                
                product_texts = []
                for product in products[:50]:
                    name = product.get('name', '')
                    desc = product.get('description', '')
                    category = product.get('category', '')
                    text = f"{name} {desc} {category}".strip()
                    product_texts.append(text)
                
                if product_texts:
                    query_embedding = self.model.encode([original_query])
                    product_embeddings = self.model.encode(product_texts)
                    similarities = cosine_similarity(query_embedding, product_embeddings)
                    
                    top_indices = np.argsort(similarities[0])[-3:]
                    terms = set([original_query])
                    
                    for idx in top_indices:
                        if similarities[0][idx] > 0.2:
                            product = products[idx]
                            name_words = product.get('name', '').lower().split()
                            terms.update(name_words[:2])
                    
                    processed_query = ' '.join(terms)
            except Exception as e:
                logger.warning(f"Query enhancement failed: {e}")
        
        return processed_query
    
    @lru_cache(maxsize=100)
    def get_semantic_suggestions(self, query: str) -> List[str]:
        """Get suggestions based on query"""
        suggestions = []
        
        categories = {
            'electronics': ['phone', 'laptop', 'computer', 'tablet', 'headphones', 'speaker'],
            'clothing': ['shirt', 'pants', 'dress', 'shoes', 'jacket', 'hat'],
            'home': ['furniture', 'decor', 'kitchen', 'bedroom', 'living room'],
            'books': ['novel', 'textbook', 'fiction', 'non-fiction', 'manual'],
            'sports': ['equipment', 'gear', 'fitness', 'outdoor', 'exercise']
        }
        
        query_lower = query.lower()
        for category, terms in categories.items():
            if any(term in query_lower for term in terms):
                suggestions.extend([f"{category} {term}" for term in terms[:3]])
                break
        
        return suggestions[:5]

class ShoppingAgent:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.semantic_engine = SemanticSearchEngine()
        self.gemini = GeminiClient(GEMINI_API_KEY)
    
    def _get_user_friendly_error(self, error_message: str, operation: str) -> str:
        """Convert technical errors to user-friendly messages"""
        error_lower = error_message.lower()
        
        # Product not found errors
        if "no product with id" in error_lower or "not found" in error_lower:
            return "Sorry, that product couldn't be found. Please try searching for products first to get valid product IDs."
        
        # Cart errors
        if operation == "cart_add":
            if "timeout" in error_lower or "connection" in error_lower:
                return "I'm having trouble connecting to the shopping cart right now. Please try again in a moment."
            elif "invalid" in error_lower:
                return "There was an issue with the product information. Please try searching for the product again."
            else:
                return "I couldn't add that item to your cart right now. Please try again or search for the product first."
        
        # Search errors  
        elif operation == "search":
            if "timeout" in error_lower:
                return "The product search is taking too long. Please try again with different keywords."
            elif "connection" in error_lower:
                return "I'm having trouble accessing the product catalog. Please try again in a moment."
            else:
                return "I couldn't search for products right now. Please try again with different keywords."
        
        # Cart view errors
        elif operation == "cart_view":
            if "timeout" in error_lower or "connection" in error_lower:
                return "I can't access your cart right now. Please try again in a moment."
            else:
                return "There was a problem loading your cart. Please try refreshing."
        
        # Product details errors
        elif operation == "product_details":
            if "no product with id" in error_lower:
                return "I couldn't find details for that product. It may no longer be available."
            elif "timeout" in error_lower or "connection" in error_lower:
                return "I'm having trouble loading product details right now. Please try again."
            else:
                return "I couldn't get the details for that product. Please try again."
        
        # Generic fallback
        if "timeout" in error_lower:
            return "The request took too long. Please try again."
        elif "connection" in error_lower or "service" in error_lower:
            return "I'm having trouble connecting to our systems. Please try again in a moment."
        else:
            return "Something went wrong. Please try again or rephrase your request."
    
    async def search_products(self, query: str, enhanced: bool = False) -> Dict[str, Any]:
        """Search products with optional semantic enhancement"""
        try:
            search_query = query
            
            if enhanced and self.semantic_engine.model:
                all_products_result = await self.list_all_products()
                if all_products_result.get("status") == "success":
                    products = all_products_result.get("products", [])
                    search_query = await self.semantic_engine.enhance_search_query(query, products)
                    logger.info(f"Enhanced query from '{query}' to '{search_query}'")
            elif enhanced:
                logger.info("Semantic enhancement requested but ML libraries not available")
            
            response = await self.client.post(
                f"{MCP_SERVER_URL}/search_products",
                json={"query": search_query}
            )
            response.raise_for_status()
            result = response.json()
            
            # Add semantic scoring if ML is available
            if enhanced and self.semantic_engine.model and result.get("results"):
                result = self._add_semantic_scores(query, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            user_friendly_message = self._get_user_friendly_error(str(e), "search")
            return {"status": "error", "message": user_friendly_message}
    
    def _add_semantic_scores(self, original_query: str, search_result: Dict) -> Dict:
        """Add semantic similarity scores - only if ML is available"""
        if not self.semantic_engine.model or not ML_AVAILABLE:
            return search_result
            
        try:
            results = search_result.get("results", [])
            if not results:
                return search_result
            
            query_embedding = self.semantic_engine.model.encode([original_query])
            
            product_texts = []
            for product in results:
                name = product.get('name', '')
                desc = product.get('description', '')
                text = f"{name} {desc}".strip() or name
                product_texts.append(text)
            
            if product_texts:
                product_embeddings = self.semantic_engine.model.encode(product_texts)
                similarities = cosine_similarity(query_embedding, product_embeddings)[0]
                
                for i, product in enumerate(results):
                    product['semantic_score'] = float(similarities[i])
                
                results.sort(key=lambda x: x.get('semantic_score', 0), reverse=True)
                search_result["results"] = results
        
        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")
        
        return search_result
    
    async def get_product_details(self, product_id: str) -> Dict[str, Any]:
        try:
            response = await self.client.post(
                f"{MCP_SERVER_URL}/get_product_details",
                json={"product_id": product_id}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Product details error: {e}")
            user_friendly_message = self._get_user_friendly_error(str(e), "product_details")
            return {"status": "error", "message": user_friendly_message}
    
    async def add_to_cart(self, user_id: str, product_id: str, quantity: int) -> Dict[str, Any]:
        if not user_id or not user_id.strip():
            return {"status": "error", "message": "User ID is required"}
        if not product_id or not product_id.strip():
            return {"status": "error", "message": "Product ID is required"}
        if quantity <= 0:
            return {"status": "error", "message": "Quantity must be greater than 0"}
            
        try:
            response = await self.client.post(
                f"{MCP_SERVER_URL}/add_item_to_cart",
                json={"user_id": user_id, "product_id": product_id, "quantity": quantity}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Add to cart error: {e}")
            user_friendly_message = self._get_user_friendly_error(str(e), "cart_add")
            return {"status": "error", "message": user_friendly_message}
    
    async def get_cart(self, user_id: str) -> Dict[str, Any]:
        try:
            response = await self.client.post(
                f"{MCP_SERVER_URL}/get_cart_contents",
                json={"user_id": user_id}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Get cart error: {e}")
            user_friendly_message = self._get_user_friendly_error(str(e), "cart_view")
            return {"status": "error", "message": user_friendly_message}
    
    async def empty_cart(self, user_id: str) -> Dict[str, Any]:
        try:
            response = await self.client.post(
                f"{MCP_SERVER_URL}/empty_cart",
                json={"user_id": user_id}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Empty cart error: {e}")
            user_friendly_message = self._get_user_friendly_error(str(e), "cart_view")
            return {"status": "error", "message": user_friendly_message}
    
    async def list_all_products(self) -> Dict[str, Any]:
        try:
            response = await self.client.get(f"{MCP_SERVER_URL}/list_products")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"List products error: {e}")
            user_friendly_message = self._get_user_friendly_error(str(e), "search")
            return {"status": "error", "message": user_friendly_message}
    
    async def process_natural_language_request(self, user_message: str, user_id: str) -> str:
        """Main processing - Gemini first, then semantic/rule-based fallback"""
        if not user_message.strip():
            return "I didn't catch that. Could you try again?"
        
        # Try Gemini processing first if available
        if self.gemini.enabled:
            try:
                return await self._process_with_gemini(user_message, user_id)
            except Exception as e:
                logger.error(f"Gemini processing failed, using fallback: {e}")
        
        # Fallback to original semantic processing
        return await self._process_with_fallback(user_message, user_id)
    
    async def _process_with_gemini(self, user_message: str, user_id: str) -> str:
        """Gemini processing with proper MCP integration"""
        
        # Get all available products from MCP server first
        all_products_result = await self.list_all_products()
        available_products = []
        if all_products_result.get("status") == "success":
            available_products = all_products_result.get("products", [])
        
        # Get cart context from MCP server
        cart_result = await self.get_cart(user_id)
        cart_context = ""
        if cart_result.get("status") == "success":
            items = cart_result.get("items", [])
            if items:
                cart_context = f"User has {len(items)} items in cart currently. "
        
        # Create product catalog context for Gemini
        product_catalog = []
        for product in available_products[:15]:  # Limit to prevent token overflow
            product_info = f"- {product.get('name', 'Unknown')} (ID: {product.get('id', '')}) - ${product.get('price', {}).get('units', 0)}.{product.get('price', {}).get('nanos', 0):02d}"
            if product.get('description'):
                product_info += f": {product.get('description', '')[:100]}"
            if product.get('categories'):
                product_info += f" [Categories: {', '.join(product.get('categories', []))}]"
            product_catalog.append(product_info)
        
        # Gemini prompt with actual product context
        prompt = f"""You are a shopping assistant for an Online Boutique. A customer said: "{user_message}"

{cart_context}

AVAILABLE PRODUCTS IN OUR STORE:
{chr(10).join(product_catalog)}

Based on what the customer wants and our available inventory:

1. If we have products that match their request:
   - Recommend specific products by name and ID in this format: "**Product Name** (ID: PRODUCTID)"
   - Explain why each product works for them
   - Include prices and key features
   - Always format product IDs clearly like (ID: PRODUCTID)

2. If we don't have what they're looking for:
   - Politely explain we don't carry that specific item
   - Suggest the closest alternatives from our inventory
   - Be helpful about what we DO have

3. For shopping requests (like "I need shoes" or "looking for a shirt"):
   - Show 2-3 best matching products with clear IDs
   - Be enthusiastic about our recommendations
   - Tell users their options for adding products

4. IMPORTANT: When recommending products, ALWAYS use this exact format:
   "**Product Name** (ID: PRODUCTID) - $X.XX"

5. After showing products, always remind users of their options:
   "To add products to your cart, you can:
   • Say 'add [PRODUCT_ID] to cart' (using the ID above)
   • Say 'add [Product Name] to cart' (using the product name)
   • Say 'add all to cart' to add all recommended products"

Be conversational, helpful, and focus only on products we actually have in stock. Make your recommendations sound appealing and confident."""

        # Check if user wants to add products to cart
        cart_intent = self._detect_cart_add_intent(user_message)
        
        if cart_intent:
            # Try to handle cart addition
            cart_result = await self._handle_cart_addition(user_message, user_id, available_products)
            if cart_result:
                return cart_result

        # Get Gemini response
        gemini_response = await self.gemini.generate_response(prompt, temperature=0.7)
        
        # Removed auto-add functionality - users will see options and choose manually
        
        # If Gemini fails, try to search and provide fallback response
        if (not gemini_response or
            len(gemini_response.strip()) < 50 or
            # "Sorry" in gemini_response or  # Removed: "Sorry" is part of good customer service responses
            "trouble" in gemini_response):
            
            # Try product search as fallback
            search_terms = self._extract_search_terms(user_message, "search")
            if search_terms:
                search_result = await self.search_products(search_terms, enhanced=True)
                
                if search_result.get("status") == "success" and search_result.get("results"):
                    products = search_result["results"][:3]
                    fallback_response = f"I found these products matching '{search_terms}':\n\n"
                    
                    for product in products:
                        price = product.get("price", {})
                        price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                        fallback_response += f"• **{product.get('name', 'Unknown')}** - {price_str}\n"
                        fallback_response += f"  ID: {product.get('id', '')} | {product.get('description', '')[:80]}...\n\n"
                    
                    fallback_response += "To add any item to your cart, just say 'add [PRODUCT_ID] to cart'!"
                    return fallback_response
                else:
                    return f"I couldn't find products matching '{search_terms}' in our current inventory. Here's what we have available: {', '.join([p.get('name', '') for p in available_products[:5]])}"
            else:
                return "I'd be happy to help you find something! Could you tell me more specifically what you're looking for?"
        
        return gemini_response
    
    async def _handle_cart_addition(self, user_message: str, user_id: str, available_products: list) -> Optional[str]:
        """Handle cart addition from chat message - supports ID, name, or 'add all'"""

        # Check for "add all" command
        if self._is_add_all_command(user_message):
            return await self._add_all_products_to_cart(user_id, available_products)

        # Check for explicit product ID
        product_id = self._extract_product_id(user_message)
        if product_id:
            # Verify product exists
            product_details = await self.get_product_details(product_id)
            if product_details.get("status") == "success":
                product = product_details.get("product", {})
                quantity = self._extract_quantity(user_message)
                result = await self.add_to_cart(user_id, product_id, quantity)
                if result.get("status") == "success":
                    price = product.get("price", {})
                    price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                    return f"Added {quantity}x **{product.get('name', '')}** ({price_str} each) to your cart!"
                else:
                    return f"Couldn't add item to cart: {result.get('message', 'Unknown error')}"
            else:
                return f"Product ID '{product_id}' not found. Please search for products to get valid IDs."

        # Try to match by product name from available products
        if available_products:
            product_by_name = self._extract_product_by_name(user_message, available_products)
            if product_by_name:
                product_id = product_by_name.get('id')
                product_name = product_by_name.get('name', 'Unknown')
                quantity = self._extract_quantity(user_message)

                result = await self.add_to_cart(user_id, product_id, quantity)
                if result.get("status") == "success":
                    price = product_by_name.get("price", {})
                    price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                    return f"Added {quantity}x **{product_name}** ({price_str} each) to your cart!"
                else:
                    return f"Found '{product_name}' but couldn't add to cart: {result.get('message', 'Unknown error')}"

        # Try to search and find best match
        search_terms = self._extract_search_terms(user_message, "cart_add")
        if search_terms and len(search_terms.strip()) > 2:
            search_result = await self.search_products(search_terms, enhanced=True)
            if search_result.get("status") == "success" and search_result.get("results"):
                products = search_result["results"]
                
                # Get the best matching product
                best_product = self._find_best_product_match(user_message, products)
                if best_product:
                    product_id = best_product.get('id')
                    quantity = self._extract_quantity(user_message)
                    
                    result = await self.add_to_cart(user_id, product_id, quantity)
                    if result.get("status") == "success":
                        price = best_product.get("price", {})
                        price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                        return f"Added {quantity}x **{best_product.get('name', 'Unknown')}** ({price_str} each) to your cart!\n\nThis was the best match for '{search_terms}'."
                    else:
                        return f"Found '{best_product.get('name', 'Unknown')}' but couldn't add to cart: {result.get('message', 'Unknown error')}"
                else:
                    # Show options
                    response = f"Found {len(products)} products for '{search_terms}':\n\n"
                    for i, product in enumerate(products[:3], 1):
                        price = product.get("price", {})
                        price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                        response += f"{i}. **{product.get('name', 'Unknown')}** - {price_str}\n"
                        response += f"   ID: `{product.get('id', '')}`\n\n"
                    
                    response += f"To add any item, say 'add {products[0].get('id', 'PRODUCT_ID')} to cart'!"
                    return response
            else:
                return f"Couldn't find products matching '{search_terms}'. Try different keywords."
        
        return None
    
    def _find_best_product_match(self, message: str, products: list) -> Optional[Dict]:
        """Find the best product match from a list based on the message"""
        message_lower = message.lower()
        
        # Look for product names mentioned in the message
        for product in products:
            product_name = product.get('name', '').lower()
            
            # Check if product name is mentioned
            if product_name and len(product_name) > 3:
                if product_name in message_lower:
                    return product
                
                # Check if most words from product name are in message
                name_words = [word for word in product_name.split() if len(word) > 2]
                if name_words:
                    matches = sum(1 for word in name_words if word in message_lower)
                    if matches >= len(name_words) * 0.7:  # 70% of name words match
                        return product
        
        # If no direct match, return the first (best scored) result
        return products[0] if products else None
    
    async def _process_with_fallback(self, user_message: str, user_id: str) -> str:
        """Semantic/rule-based processing as fallback with MCP integration"""
        
        # Get all available products from MCP first
        all_products_result = await self.list_all_products()
        available_products = []
        if all_products_result.get("status") == "success":
            available_products = all_products_result.get("products", [])
        
        processed_msg = self.semantic_engine.preprocess_text(user_message)
        entities = self.semantic_engine.extract_entities(user_message)
        intent = self.semantic_engine.classify_intent(user_message)
        
        try:
            if intent == 'search':
                search_terms = self._extract_search_terms(user_message, intent)
                
                if search_terms:
                    enhanced = self.semantic_engine.model is not None
                    result = await self.search_products(search_terms, enhanced=enhanced)
                    
                    if result.get("status") == "success" and result.get("results"):
                        products = result["results"][:5]
                        response = f"I found {len(products)} products in our boutique matching '{search_terms}':\n\n"
                        
                        for i, p in enumerate(products, 1):
                            price = p.get("price", {})
                            price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}" if price else "Price not available"
                            
                            response += f"{i}. **{p.get('name', 'Unknown Product')}** - {price_str}\n"
                            response += f"   ID: `{p.get('id', '')}` | Categories: {', '.join(p.get('categories', []))}\n"
                            
                            desc = p.get('description', '')
                            if desc:
                                response += f"   {desc[:80]}{'...' if len(desc) > 80 else ''}\n"
                            response += f"   Say 'add {p.get('id', '')} to cart' to purchase!\n\n"
                        
                        return response
                    else:
                        # No results found, suggest alternatives from available products
                        if available_products:
                            response = f"I couldn't find products matching '{search_terms}' in our boutique.\n\n"
                            response += "Here's what we have available:\n"
                            for i, product in enumerate(available_products[:5], 1):
                                price = product.get("price", {})
                                price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                                response += f"{i}. {product.get('name', '')} - {price_str} (ID: {product.get('id', '')})\n"
                            return response
                        else:
                            return "Sorry, I couldn't find any products matching your search."
                else:
                    return "What would you like me to search for? Try something like 'show me watches' or 'find kitchen items'."
            
            elif intent == 'cart_add':
                product_id = self._extract_product_id(user_message)
                if product_id:
                    # Verify product exists before adding
                    product_details = await self.get_product_details(product_id)
                    if product_details.get("status") == "success":
                        product = product_details.get("product", {})
                        quantity = self._extract_quantity(user_message)
                        result = await self.add_to_cart(user_id, product_id, quantity)
                        if result.get("status") == "success":
                            price = product.get("price", {})
                            price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                            return f"Added {quantity}x {product.get('name', '')} ({price_str} each) to your cart!"
                        else:
                            return f"Couldn't add item to cart: {result.get('message', 'Unknown error')}"
                    else:
                        return f"Product ID '{product_id}' not found. Please search for products to get valid IDs."
                else:
                    return "To add items to cart, please specify the product ID. Example: 'add OLJCESPC7Z to cart'\n\nSearch for products first to get their IDs!"
            
            elif intent == 'cart_view':
                result = await self.get_cart(user_id)
                if result.get("status") == "success":
                    items = result.get("items", [])
                    if items:
                        response = f"Your shopping cart ({len(items)} unique items):\n\n"
                        total_value = 0
                        total_items = 0
                        
                        for item in items:
                            qty = item.get('quantity', 1)
                            total_items += qty
                            product_id = item.get('product_id', '')
                            
                            # Get product details for each item
                            product_details = await self.get_product_details(product_id)
                            if product_details.get("status") == "success":
                                product = product_details.get("product", {})
                                price = product.get("price", {})
                                units = price.get('units', 0)
                                nanos = price.get('nanos', 0)
                                item_price = float(units) + float(nanos) / 1000000000
                                item_total = item_price * qty
                                total_value += item_total
                                
                                response += f"• **{product.get('name', 'Unknown')}** x{qty}\n"
                                response += f"  ${item_price:.2f} each = ${item_total:.2f}\n"
                                response += f"  ID: {product_id}\n\n"
                            else:
                                response += f"• Product {product_id} x{qty} (details unavailable)\n\n"
                        
                        response += f"**Total: {total_items} items, ${total_value:.2f}**\n\n"
                        response += "Say 'remove [PRODUCT_ID] from cart' to remove items!"
                        return response
                    else:
                        return "Your cart is empty. Search for products to add!\n\nTry: 'show me watches' or 'find kitchen items'"
                else:
                    return "Couldn't access your cart right now. Please try again."
            
            elif intent == 'recommendations':
                budget = self._extract_budget(user_message)
                result = await self.list_all_products()
                
                if result.get("status") == "success" and result.get("products"):
                    products = result["products"]
                    
                    if budget:
                        filtered_products = []
                        for p in products:
                            price = p.get("price", {})
                            if price:
                                total = float(price.get("units", 0)) + float(price.get("nanos", 0)) / 1000000000
                                if total <= budget:
                                    filtered_products.append(p)
                        products = filtered_products
                    
                    recommendations = products[:6]
                    
                    budget_text = f" under ${budget}" if budget else ""
                    response = f"Here are my top recommendations{budget_text}:\n\n"
                    
                    for i, p in enumerate(recommendations, 1):
                        price = p.get("price", {})
                        price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}" if price else "Price N/A"
                        
                        response += f"{i}. {p.get('name', 'Unknown')} - {price_str}\n"
                        desc = p.get('description', '')
                        if desc:
                            response += f"   {desc[:80]}{'...' if len(desc) > 80 else ''}\n"
                        response += f"   ID: {p.get('id', '')}\n\n"
                    
                    return response
                else:
                    return "Can't get recommendations right now. Please try again later."
            
            elif intent == 'help':
                mode = "with Gemini AI" if self.gemini.enabled else "with semantic search" if self.semantic_engine.model else "with basic matching"
                return f"""I'm your shopping assistant {mode}! Here's what I can do:

Search Products:
• "business shoes for meetings"
• "casual shirts for weekend"  
• "blue dress under $50"

Cart Management:
• "show my cart" or "view basket"
• "add PRODUCT_ID to cart"
• "buy 2 of PRODUCT_ID"

Get Recommendations:
• "recommend something"
• "suggest items under $100"
• "what's popular?"

Product Details:
• "tell me about PRODUCT_ID"

Just tell me what you need naturally!"""
            
            else:
                return f"I can help you find products, manage your cart, or get recommendations. What are you looking for?"
        
        except Exception as e:
            logger.error(f"Error processing request: {e}")
            return "I'm having trouble understanding your request right now. Could you try rephrasing it or ask me for help to see what I can do?"
    
    def _extract_search_terms(self, message: str, intent: str) -> str:
        """Extract search terms from message with better cleaning"""
        terms_to_remove = [
            'search for', 'find', 'look for', 'show me', 'get me',
            'i need', 'i want', 'looking for', 'searching for',
            'where can i find', 'do you have', 'can you find'
        ]
        
        # Additional terms to remove for cart_add intent
        if intent == "cart_add":
            terms_to_remove.extend([
                'add to cart', 'add to my cart', 'add this to cart', 'add that to cart',
                'buy this', 'buy that', 'purchase this', 'purchase that',
                'put in cart', 'add', 'to cart', 'to my cart', 'buy', 'purchase',
                'i\'ll take', 'get this', 'get that'
            ])
        
        msg = message.lower().strip()
        
        # Remove common phrases
        for term in terms_to_remove:
            msg = re.sub(r'\b' + re.escape(term) + r'\b', ' ', msg)
        
        # Remove extra whitespace
        msg = re.sub(r'\s+', ' ', msg).strip()
        
        # Remove very short words (unless the whole query is short)
        words = msg.split()
        if len(words) > 2:
            words = [word for word in words if len(word) > 2]
            msg = ' '.join(words)
        
        return msg
    
    def _extract_relevant_description(self, description: str, search_terms: str, context_modifiers: List[str]) -> str:
        """Extract relevant parts of product description"""
        if len(description) <= 100:
            return description
        
        sentences = description.split('.')
        relevant_sentences = []
        
        search_words = search_terms.lower().split()
        all_terms = search_words + [mod.lower() for mod in context_modifiers]
        
        for sentence in sentences:
            sentence = sentence.strip()
            if any(term in sentence.lower() for term in all_terms):
                relevant_sentences.append(sentence)
        
        if relevant_sentences:
            result = '. '.join(relevant_sentences[:2])
            return result[:100] + ('...' if len(result) > 100 else '')
        else:
            return description[:100] + ('...' if len(description) > 100 else '')
    
    def _get_alternative_search_terms(self, original_terms: str, entities: Dict) -> List[str]:
        """Suggest alternative search terms"""
        alternatives = []
        
        # Category alternatives
        category_map = {
            'shoes': ['footwear', 'sneakers', 'boots'],
            'shirt': ['tops', 'clothing', 'apparel'],
            'pants': ['bottoms', 'trousers', 'clothing'],
            'laptop': ['computer', 'electronics', 'technology']
        }
        
        for product_keyword in entities.get('product_types', []):
            if product_keyword in category_map:
                alternatives.extend(category_map[product_keyword])
        
        # Suggest removing context if too specific
        if len(original_terms.split()) > 2:
            alternatives.append(original_terms.split()[0])
        
        return alternatives[:3]
    
    def _extract_product_id(self, message: str) -> Optional[str]:
        """Extract product ID from message - improved to work with search results"""
        patterns = [
            r'(?:id|product)\s*:?\s*([A-Z0-9_-]{8,15})',
            r'`([A-Z0-9_-]{8,15})`',
            r'\b([A-Z0-9_-]{8,15})\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                candidate_id = match.group(1)
                # Validate it looks like a real product ID
                if (len(candidate_id) >= 8 and 
                    not candidate_id.lower() in ['mug', 'shirt', 'shoes', 'watch', 'bag', 'pants', 'dress', 'tank', 'tops'] and
                    any(c.isupper() or c.isdigit() for c in candidate_id)):
                    return candidate_id
        return None
    
    def _extract_quantity(self, message: str) -> int:
        """Extract quantity from message"""
        quantity_patterns = [
            r'(?:buy|add|get|purchase)\s+(\d+)',
            r'(\d+)\s+(?:of|items?|pieces?)',
            r'quantity\s*:?\s*(\d+)'
        ]
        
        for pattern in quantity_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return max(1, int(match.group(1)))
        
        return 1
    
    def _extract_budget(self, message: str) -> Optional[float]:
        """Extract budget from message"""
        patterns = [
            r'under\s*\$?(\d+(?:\.\d{2})?)',
            r'below\s*\$?(\d+(?:\.\d{2})?)',
            r'less than\s*\$?(\d+(?:\.\d{2})?)',
            r'budget\s*:?\s*\$?(\d+(?:\.\d{2})?)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return float(match.group(1))
        
        return None
    
    def _detect_cart_add_intent(self, message: str) -> bool:
        """Detect if user wants to add something to cart"""
        cart_add_patterns = [
            'add to cart', 'add this to cart', 'add it to cart', 'add that to cart',
            'buy this', 'buy that', 'buy it', 'purchase this', 'purchase that',
            'get this', 'get that', 'i want this', 'i want that', 'i\'ll take it',
            'i\'ll take this', 'i\'ll take that', 'put in cart', 'add to my cart',
            'i need', 'i want', 'looking for', 'need some', 'want some',
            'find me', 'get me', 'i\'d like', 'i require', 'shopping for',
            'for work', 'for meeting', 'for office', 'for business', 'for running',
            'for gym', 'for exercise', 'for jogging', 'for walking', 'for casual',
            'for weekend', 'for formal', 'for interview', 'for presentation'
        ]
        
        message_lower = message.lower()
        
        # Check explicit patterns
        if any(pattern in message_lower for pattern in cart_add_patterns):
            return True
            
        # Check for "add [product] to cart" patterns with product names in between
        if re.search(r'\badd\s+\w+.*?to\s+cart\b', message_lower) or re.search(r'\badd\s+.*?to\s+my\s+cart\b', message_lower):
            return True
            
        # Check for simple product requests (short messages with product types)
        product_types = ['shoes', 'shirt', 'pants', 'dress', 'jacket', 'watch', 'bag', 'headphones']
        has_product_mention = any(product in message_lower for product in product_types)
        
        # If message is short and mentions a product, likely wants to add it
        if has_product_mention and len(message.split()) <= 8:
            return True
            
        return False
    
    def _is_product_recommendation(self, response: str) -> bool:
        """Check if response contains product recommendations"""
        recommendation_indicators = [
            'recommend', 'suggest', 'perfect for', 'great choice', 'ideal for',
            '(ID:', 'product id', 'here are some', 'i found', 'try these'
        ]
        
        response_lower = response.lower()
        return any(indicator in response_lower for indicator in recommendation_indicators)
    
    def _extract_product_ids_from_response(self, response: str) -> list:
        """Extract product IDs from response"""
        patterns = [
            r'\(ID:\s*([A-Z0-9_-]+)\)',
            r'ID:\s*([A-Z0-9_-]+)',
            r'Product ID:\s*([A-Z0-9_-]+)',
            r'`([A-Z0-9_-]+)`'
        ]
        
        found_ids = []
        for pattern in patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            found_ids.extend(matches)
        
        return found_ids
    
    def _user_wants_recommended_products(self, message: str) -> bool:
        """Check if user wants products based on description"""
        product_request_indicators = [
            'add to cart', 'buy this', 'buy that', 'buy these', 'purchase this', 
            'purchase that', 'purchase these', 'i\'ll take it', 'i\'ll take this',
            'i\'ll take that', 'i\'ll take these', 'add this to cart', 'add that to cart',
            'add these to cart', 'put in cart', 'get this', 'get that', 'get these',
            'i need', 'i want', 'looking for', 'need some', 'want some',
            'find me', 'get me', 'show me', 'i\'d like', 'i require',
            'for work', 'for meeting', 'for office', 'for business', 'for running',
            'for gym', 'for exercise', 'for jogging', 'for walking', 'for casual',
            'for weekend', 'for formal', 'for interview', 'for presentation'
        ]
        
        message_lower = message.lower()
        
        # Check explicit patterns first
        if any(indicator in message_lower for indicator in product_request_indicators):
            return True
        
        # Check for "add [product] to cart" patterns with product names in between
        if re.search(r'\badd\s+\w+.*?to\s+cart\b', message_lower) or re.search(r'\badd\s+.*?to\s+my\s+cart\b', message_lower):
            return True
        
        # Also check for simple product mentions without explicit verbs
        product_types = ['shoes', 'shirt', 'pants', 'dress', 'jacket', 'watch', 'bag', 'headphones', 'mug']
        has_product_mention = any(product in message_lower for product in product_types)
        
        # If message is short and mentions a product type, likely wants it
        if has_product_mention and len(message.split()) <= 6:
            return True
            
        return False

    def _is_add_all_command(self, message: str) -> bool:
        """Check if user wants to add all products to cart"""
        message_lower = message.lower()
        add_all_patterns = [
            'add all', 'add all products', 'add all items', 'add everything',
            'add all to cart', 'add all products to cart', 'add all items to cart',
            'buy all', 'purchase all', 'get all', 'take all'
        ]
        return any(pattern in message_lower for pattern in add_all_patterns)

    async def _add_all_products_to_cart(self, user_id: str, available_products: list) -> str:
        """Add all available products from the last response to cart"""
        if not available_products:
            return "No products are currently available to add to cart."

        added_products = []
        failed_products = []

        # Limit to first 5 products to avoid overwhelming cart
        products_to_add = available_products[:5]

        for product in products_to_add:
            product_id = product.get('id', '')
            product_name = product.get('name', 'Unknown')

            if product_id:
                result = await self.add_to_cart(user_id, product_id, 1)
                if result.get("status") == "success":
                    price = product.get("price", {})
                    price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                    added_products.append(f"• **{product_name}** - {price_str}")
                else:
                    failed_products.append(product_name)

        response = ""
        if added_products:
            response += f"Added {len(added_products)} products to your cart:\n\n"
            response += "\n".join(added_products)

        if failed_products:
            response += f"\n\nCouldn't add these products: {', '.join(failed_products)}"

        if not added_products and not failed_products:
            response = "No valid products found to add to cart."

        return response

    def _extract_product_by_name(self, message: str, available_products: list) -> Optional[Dict]:
        """Extract product by matching name from available products"""
        message_lower = message.lower()

        # Remove common cart-related words to get product name
        cart_words = ['add', 'to', 'cart', 'buy', 'purchase', 'get', 'take']
        words = [word for word in message_lower.split() if word not in cart_words and len(word) > 2]

        if not words:
            return None

        search_text = ' '.join(words)

        # Find best matching product by name
        best_match = None
        best_score = 0

        for product in available_products:
            product_name = product.get('name', '').lower()

            # Check for exact matches or high similarity
            if search_text in product_name or product_name in search_text:
                # Exact substring match gets high score
                score = 0.9
            else:
                # Calculate word overlap score
                product_words = product_name.split()
                common_words = set(words) & set(product_words)
                if common_words:
                    score = len(common_words) / max(len(words), len(product_words))
                else:
                    score = 0

            if score > best_score and score > 0.3:  # Minimum threshold
                best_score = score
                best_match = product

        return best_match

# Initialize shopping agent
shopping_agent = ShoppingAgent()

@app.post("/chat")
async def chat_with_concierge(request: ConversationRequest):
    """Chat endpoint with Gemini + semantic search + complete fallback"""
    try:
        if not request.messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_msg = request.messages[-1]
        if last_msg.role != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")
        
        response_text = await shopping_agent.process_natural_language_request(
            last_msg.content, 
            request.user_id
        )
        
        return {
            "response": response_text,
            "user_id": request.user_id,
            "status": "success",
            "gemini_enabled": shopping_agent.gemini.enabled,
            "semantic_enhanced": shopping_agent.semantic_engine.model is not None,
            "processing_mode": "gemini" if shopping_agent.gemini.enabled else "semantic_fallback"
        }
    
    except Exception as e:
        logger.error(f"Chat error: {e}")
        user_friendly_error = shopping_agent._get_user_friendly_error(str(e), "search")
        raise HTTPException(status_code=500, detail=user_friendly_error)

@app.post("/search")
async def search_products(request: ProductQuery):
    """Search endpoint with semantic capabilities"""
    enhanced = shopping_agent.semantic_engine.model is not None
    result = await shopping_agent.search_products(request.query, enhanced=enhanced)
    if result.get("status") == "error":
        user_friendly_error = shopping_agent._get_user_friendly_error(result.get("message", "Search failed"), "search")
        raise HTTPException(status_code=500, detail=user_friendly_error)
    return result

@app.post("/cart/action")
async def cart_action(request: CartActionRequest):
    try:
        if request.action == "add" and request.product_id:
            result = await shopping_agent.add_to_cart(
                request.user_id, 
                request.product_id, 
                request.quantity or 1
            )
        elif request.action == "view":
            result = await shopping_agent.get_cart(request.user_id)
        elif request.action == "clear":
            result = await shopping_agent.empty_cart(request.user_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        if result.get("status") == "error":
            operation = "cart_add" if request.action == "add" else "cart_view"
            user_friendly_error = shopping_agent._get_user_friendly_error(result.get("message", "Action failed"), operation)
            raise HTTPException(status_code=500, detail=user_friendly_error)
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cart action error: {e}")
        user_friendly_error = shopping_agent._get_user_friendly_error(str(e), "cart_view")
        raise HTTPException(status_code=500, detail=user_friendly_error)

@app.post("/recommendations")
async def get_recommendations(request: ProductRecommendationRequest):
    try:
        result = await shopping_agent.list_all_products()
        
        if result.get("status") == "error":
            user_friendly_error = shopping_agent._get_user_friendly_error(result.get("message", "Recommendations failed"), "search")
            raise HTTPException(status_code=500, detail=user_friendly_error)
        
        products = result.get("products", [])
        
        # Apply budget filter
        if request.budget_max:
            filtered = []
            for p in products:
                price = p.get("price", {})
                if price:
                    total = float(price.get("units", 0)) + float(price.get("nanos", 0)) / 1000000000
                    if total <= request.budget_max:
                        filtered.append(p)
            products = filtered
        
        recommendations = products[:10]
        
        return {
            "status": "success",
            "recommendations": recommendations,
            "count": len(recommendations),
            "user_id": request.user_id,
            "semantic_enhanced": shopping_agent.semantic_engine.model is not None
        }
    
    except Exception as e:
        logger.error(f"Recommendations error: {e}")
        user_friendly_error = shopping_agent._get_user_friendly_error(str(e), "search")
        raise HTTPException(status_code=500, detail=user_friendly_error)

@app.get("/health")
async def health_check():
    # Test MCP connection
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{MCP_SERVER_URL}/health")
            mcp_ok = response.status_code == 200
    except:
        mcp_ok = False
    
    return {
        "status": "healthy",
        "service": "adk-agents",
        "version": "2.0.0",
        "mcp_server": "ok" if mcp_ok else "down",
        "gemini_api": "enabled" if shopping_agent.gemini.enabled else "disabled", 
        "semantic_search": "enabled" if shopping_agent.semantic_engine.model else "disabled",
        "nlp_processor": "advanced" if shopping_agent.semantic_engine.nlp else "basic",
        "ml_libraries": "available" if ML_AVAILABLE else "not available",
        "spacy": "available" if SPACY_AVAILABLE else "not available"
    }

@app.get("/")
async def root():
    features = []
    if shopping_agent.gemini.enabled:
        features.append("Gemini AI")
    if ML_AVAILABLE:
        features.append("Semantic search")
    if SPACY_AVAILABLE:
        features.append("Advanced NLP")
    if not features:
        features.append("Basic keyword matching")
    
    return {
        "service": "ADK Shopping Concierge",
        "version": "2.0.0", 
        "status": "running",
        "description": f"AI shopping assistant with {', '.join(features)}",
        "features": features + [
            "Natural language understanding", 
            "Intent classification",
            "Product search and recommendations",
            "Cart management"
        ],
        "endpoints": [
            "/chat", "/search", "/cart/action", "/recommendations", "/health", "/docs", "/debug"
        ]
    }

@app.post("/debug")
async def debug_conversation(request: ConversationRequest):
    """Debug endpoint showing all interactions, responses, and decision points"""
    debug_info = {
        "timestamp": str(asyncio.get_event_loop().time()),
        "user_input": request.messages[-1].content if request.messages else "",
        "user_id": request.user_id,
        "steps": [],
        "final_response": "",
        "gemini_enabled": shopping_agent.gemini.enabled,
        "ml_available": ML_AVAILABLE,
        "semantic_engine_available": shopping_agent.semantic_engine.model is not None
    }

    try:
        user_message = request.messages[-1].content
        debug_info["steps"].append({"step": "1_input_received", "data": user_message})

        # Get all available products from MCP server first
        debug_info["steps"].append({"step": "2_fetching_products", "data": "Getting available products from MCP server"})
        all_products_result = await shopping_agent.list_all_products()
        available_products = []
        if all_products_result.get("status") == "success":
            available_products = all_products_result.get("products", [])

        debug_info["steps"].append({
            "step": "3_products_fetched",
            "data": {
                "product_count": len(available_products),
                "product_names": [p.get('name', '') for p in available_products[:10]]
            }
        })

        # Get cart context
        debug_info["steps"].append({"step": "4_fetching_cart", "data": "Getting cart context"})
        cart_result = await shopping_agent.get_cart(request.user_id)
        cart_context = ""
        if cart_result.get("status") == "success":
            items = cart_result.get("items", [])
            if items:
                cart_context = f"User has {len(items)} items in cart currently. "

        debug_info["steps"].append({
            "step": "5_cart_context",
            "data": {"cart_context": cart_context, "cart_items": cart_result.get("items", [])}
        })

        # Create product catalog context for Gemini
        product_catalog = []
        for product in available_products[:15]:
            product_info = f"- {product.get('name', 'Unknown')} (ID: {product.get('id', '')}) - ${product.get('price', {}).get('units', 0)}.{product.get('price', {}).get('nanos', 0):02d}"
            if product.get('description'):
                product_info += f": {product.get('description', '')[:100]}"
            if product.get('categories'):
                product_info += f" [Categories: {', '.join(product.get('categories', []))}]"
            product_catalog.append(product_info)

        debug_info["steps"].append({
            "step": "6_product_catalog_prepared",
            "data": {"catalog_entries": len(product_catalog), "catalog_preview": product_catalog[:3]}
        })

        # Build Gemini prompt
        prompt = f"""You are a shopping assistant for an Online Boutique. A customer said: "{user_message}"

{cart_context}

AVAILABLE PRODUCTS IN OUR STORE:
{chr(10).join(product_catalog)}

Based on what the customer wants and our available inventory:

1. If we have products that match their request:
   - Recommend specific products by name and ID in this format: "**Product Name** (ID: PRODUCTID)"
   - Explain why each product works for them
   - Include prices and key features
   - Always format product IDs clearly like (ID: PRODUCTID)

2. If we don't have what they're looking for:
   - Politely explain we don't carry that specific item
   - Suggest the closest alternatives from our inventory
   - Be helpful about what we DO have

3. For shopping requests (like "I need shoes" or "looking for a shirt"):
   - Show 2-3 best matching products with clear IDs
   - Be enthusiastic about our recommendations
   - Tell users their options for adding products

4. IMPORTANT: When recommending products, ALWAYS use this exact format:
   "**Product Name** (ID: PRODUCTID) - $X.XX"

5. After showing products, always remind users of their options:
   "To add products to your cart, you can:
   • Say 'add [PRODUCT_ID] to cart' (using the ID above)
   • Say 'add [Product Name] to cart' (using the product name)
   • Say 'add all to cart' to add all recommended products"

Be conversational, helpful, and focus only on products we actually have in stock. Make your recommendations sound appealing and confident."""

        debug_info["steps"].append({
            "step": "7_gemini_prompt_built",
            "data": {"prompt_length": len(prompt), "prompt": prompt}
        })

        # Check cart intent detection
        cart_intent = shopping_agent._detect_cart_add_intent(user_message)
        debug_info["steps"].append({
            "step": "8_cart_intent_detected",
            "data": {"cart_intent": cart_intent}
        })

        # Call Gemini if enabled
        gemini_response = ""
        if shopping_agent.gemini.enabled:
            debug_info["steps"].append({"step": "9_calling_gemini", "data": "Sending prompt to Gemini API"})
            gemini_response = await shopping_agent.gemini.generate_response(prompt, temperature=0.7)
            debug_info["steps"].append({
                "step": "10_gemini_response",
                "data": {
                    "response_length": len(gemini_response) if gemini_response else 0,
                    "response": gemini_response,
                    "response_empty": not gemini_response,
                    "response_short": len(gemini_response.strip()) < 50 if gemini_response else True,
                    "contains_sorry": "Sorry" in gemini_response if gemini_response else False,
                    "contains_trouble": "trouble" in gemini_response if gemini_response else False
                }
            })
        else:
            debug_info["steps"].append({"step": "9_gemini_disabled", "data": "Gemini API not available"})

        # Check fallback condition
        fallback_triggered = (not gemini_response or
                            len(gemini_response.strip()) < 50 or
                            "trouble" in gemini_response)

        debug_info["steps"].append({
            "step": "11_fallback_check",
            "data": {
                "fallback_triggered": fallback_triggered,
                "reason": {
                    "no_response": not gemini_response,
                    "too_short": len(gemini_response.strip()) < 50 if gemini_response else False,
                    "contains_trouble": "trouble" in gemini_response if gemini_response else False
                }
            }
        })

        final_response = ""
        if fallback_triggered:
            debug_info["steps"].append({"step": "12_using_fallback", "data": "Using fallback logic"})
            search_terms = shopping_agent._extract_search_terms(user_message, "search")
            debug_info["steps"].append({"step": "13_search_terms_extracted", "data": {"search_terms": search_terms}})

            if search_terms:
                search_result = await shopping_agent.search_products(search_terms, enhanced=True)
                debug_info["steps"].append({
                    "step": "14_search_results",
                    "data": {
                        "search_status": search_result.get("status"),
                        "result_count": len(search_result.get("results", [])),
                        "results": search_result.get("results", [])[:3]
                    }
                })

                if search_result.get("status") == "success" and search_result.get("results"):
                    products = search_result["results"][:3]
                    final_response = f"I found these products matching '{search_terms}':\n\n"
                    for product in products:
                        price = product.get("price", {})
                        price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}"
                        final_response += f"• **{product.get('name', 'Unknown')}** - {price_str}\n"
                        final_response += f"  ID: {product.get('id', '')} | {product.get('description', '')[:80]}...\n\n"
                    final_response += "To add any item to your cart, just say 'add [PRODUCT_ID] to cart'!"
                else:
                    final_response = f"I couldn't find products matching '{search_terms}' in our current inventory. Here's what we have available: {', '.join([p.get('name', '') for p in available_products[:5]])}"
            else:
                final_response = "I'd be happy to help you find something! Could you tell me more specifically what you're looking for?"
        else:
            debug_info["steps"].append({"step": "12_using_gemini_response", "data": "Using Gemini response directly"})
            final_response = gemini_response

        debug_info["final_response"] = final_response
        debug_info["steps"].append({"step": "15_final_response", "data": final_response})

        return debug_info

    except Exception as e:
        debug_info["error"] = str(e)
        debug_info["steps"].append({"step": "error", "data": str(e)})
        return debug_info

@app.get("/test_gemini")
async def test_gemini():
    if not shopping_agent.gemini.enabled:
        return {"status": "disabled", "message": "No Gemini API key"}

    try:
        test_response = await shopping_agent.gemini.generate_response("Hello! Confirm you're working for shopping assistance.")
        return {
            "status": "working",
            "gemini_response": test_response,
            "api_key_present": GEMINI_API_KEY is not None
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}