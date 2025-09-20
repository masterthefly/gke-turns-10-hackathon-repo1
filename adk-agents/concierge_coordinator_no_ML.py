import httpx
import json
import logging
import re
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
    action: str  # add, view, remove, clear
    product_id: Optional[str] = None
    quantity: Optional[int] = 1

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
        
        # Convert to lowercase
        text = text.lower().strip()
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Simple stop word removal (basic version without advanced NLP)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        words = text.split()
        words = [w for w in words if w not in stop_words or len(words) <= 3]
        
        return ' '.join(words)
    
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
        
        # Basic entity extraction without spaCy
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
        
        # If spaCy is available, add advanced entity extraction
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
        """Classify user intent - basic keyword matching, enhanced with ML if available"""
        text_lower = text.lower()
        
        # Basic keyword matching (always available)
        for intent, patterns in self.intent_patterns.items():
            if any(pattern in text_lower for pattern in patterns):
                return intent
        
        # Advanced semantic classification if ML is available
        if self.model and ML_AVAILABLE:
            try:
                query_embedding = self.model.encode([text])
                best_intent = 'search'  # default
                best_score = 0
                
                for intent, patterns in self.intent_patterns.items():
                    pattern_embeddings = self.model.encode(patterns)
                    similarities = cosine_similarity(query_embedding, pattern_embeddings)
                    max_similarity = np.max(similarities)
                    
                    if max_similarity > best_score:
                        best_score = max_similarity
                        best_intent = intent
                
                # Only return classified intent if confidence is high enough
                if best_score > 0.3:
                    return best_intent
            except Exception as e:
                logger.warning(f"Semantic intent classification failed: {e}")
        
        return 'search'  # default fallback
    
    async def enhance_search_query(self, original_query: str, products: List[Dict]) -> str:
        """Enhance search query - basic preprocessing always, semantic enhancement if ML available"""
        # Basic preprocessing (always available)
        enhanced_query = self.preprocess_text(original_query)
        
        # Semantic enhancement if ML libraries are available
        if self.model and ML_AVAILABLE and products:
            try:
                # Extract entities from query
                entities = self.extract_entities(original_query)
                
                # Get product texts for similarity matching
                product_texts = []
                for product in products[:50]:  # Limit to first 50 for performance
                    name = product.get('name', '')
                    desc = product.get('description', '')
                    category = product.get('category', '')
                    text = f"{name} {desc} {category}".strip()
                    product_texts.append(text)
                
                # Semantic similarity matching
                if product_texts:
                    query_embedding = self.model.encode([original_query])
                    product_embeddings = self.model.encode(product_texts)
                    similarities = cosine_similarity(query_embedding, product_embeddings)
                    
                    # Get top similar products and extract keywords
                    top_indices = np.argsort(similarities[0])[-3:]  # Top 3
                    enhanced_terms = set([original_query])
                    
                    for idx in top_indices:
                        if similarities[0][idx] > 0.2:  # Relevance threshold
                            product = products[idx]
                            name_words = product.get('name', '').lower().split()
                            enhanced_terms.update(name_words[:2])  # Add first 2 words
                    
                    enhanced_query = ' '.join(enhanced_terms)
            except Exception as e:
                logger.warning(f"Query enhancement failed: {e}")
        
        return enhanced_query
    
    @lru_cache(maxsize=100)
    def get_semantic_suggestions(self, query: str) -> List[str]:
        """Get suggestions based on query - basic category matching"""
        suggestions = []
        
        # Basic category suggestions (always available)
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
    
    async def search_products(self, query: str, enhanced: bool = False) -> Dict[str, Any]:
        """Search products with optional semantic enhancement"""
        try:
            search_query = query
            
            if enhanced and self.semantic_engine.model:
                # Get all products for semantic enhancement
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
            return {"status": "error", "message": str(e)}
    
    def _add_semantic_scores(self, original_query: str, search_result: Dict) -> Dict:
        """Add semantic similarity scores - only if ML is available"""
        if not self.semantic_engine.model or not ML_AVAILABLE:
            return search_result
            
        try:
            results = search_result.get("results", [])
            if not results:
                return search_result
            
            # Create embeddings
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
                
                # Add scores and sort by semantic relevance
                for i, product in enumerate(results):
                    product['semantic_score'] = float(similarities[i])
                
                # Sort by semantic score (descending)
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
            return {"status": "error", "message": str(e)}
    
    async def add_to_cart(self, user_id: str, product_id: str, quantity: int) -> Dict[str, Any]:
        try:
            response = await self.client.post(
                f"{MCP_SERVER_URL}/add_item_to_cart",
                json={"user_id": user_id, "product_id": product_id, "quantity": quantity}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Add to cart error: {e}")
            return {"status": "error", "message": str(e)}
    
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
            return {"status": "error", "message": str(e)}
    
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
            return {"status": "error", "message": str(e)}
    
    async def list_all_products(self) -> Dict[str, Any]:
        try:
            response = await self.client.get(f"{MCP_SERVER_URL}/list_products")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"List products error: {e}")
            return {"status": "error", "message": str(e)}
    
    async def process_natural_language_request(self, user_message: str, user_id: str) -> str:
        """Process user message with optional semantic understanding"""
        if not user_message.strip():
            return "I didn't catch that. Could you try again?"
        
        # Preprocess the message
        processed_msg = self.semantic_engine.preprocess_text(user_message)
        
        # Extract entities for context
        entities = self.semantic_engine.extract_entities(user_message)
        
        # Classify intent
        intent = self.semantic_engine.classify_intent(user_message)
        
        logger.info(f"User: '{user_message}' -> Intent: {intent}, Entities: {entities}")
        
        try:
            if intent == 'search':
                search_terms = self._extract_search_terms(user_message, intent)
                
                if search_terms:
                    # Use enhanced search if ML is available
                    enhanced = self.semantic_engine.model is not None
                    result = await self.search_products(search_terms, enhanced=enhanced)
                    
                    if result.get("status") == "success" and result.get("results"):
                        products = result["results"][:5]  # Top 5
                        response = f"I found {len(products)} products matching '{search_terms}':\n\n"
                        
                        for i, p in enumerate(products, 1):
                            price = p.get("price", {})
                            price_str = f"${price.get('units', 0)}.{price.get('nanos', 0):02d}" if price else "Price not available"
                            
                            # Show semantic score if available
                            score_info = ""
                            if 'semantic_score' in p and p['semantic_score'] > 0:
                                score_info = f" (Match: {p['semantic_score']:.1%})"
                            
                            response += f"{i}. {p.get('name', 'Unknown Product')} - {price_str}{score_info}\n"
                            
                            # Add description if available
                            desc = p.get('description', '')
                            if desc:
                                response += f"   {desc[:100]}{'...' if len(desc) > 100 else ''}\n"
                            
                            response += f"   ID: {p.get('id', '')}\n\n"
                        
                        # Add suggestions if available
                        suggestions = self.semantic_engine.get_semantic_suggestions(search_terms)
                        if suggestions:
                            response += f"\nRelated searches: {', '.join(suggestions[:3])}"
                        
                        return response
                    else:
                        return f"I couldn't find products matching '{search_terms}'. Try different keywords or ask me to show all products."
                else:
                    return "What would you like me to search for? Try something like 'find laptops' or 'show me shirts'."
            
            elif intent == 'cart_add':
                product_id = self._extract_product_id(user_message)
                if product_id:
                    quantity = self._extract_quantity(user_message)
                    result = await self.add_to_cart(user_id, product_id, quantity)
                    if result.get("status") == "success":
                        return f"Added {quantity} item(s) to your cart! Use 'show cart' to see all items."
                    else:
                        return f"Couldn't add item to cart: {result.get('message', 'Unknown error')}"
                else:
                    return "To add items to cart, please specify the product ID. Search for products first to get their IDs."
            
            elif intent == 'cart_view':
                result = await self.get_cart(user_id)
                if result.get("status") == "success":
                    items = result.get("items", [])
                    if items:
                        response = f"Your cart has {len(items)} item(s):\n\n"
                        total_items = 0
                        for item in items:
                            qty = item.get('quantity', 1)
                            total_items += qty
                            response += f"• Product ID: {item.get('product_id')} - Quantity: {qty}\n"
                        response += f"\nTotal items: {total_items}"
                        return response
                    else:
                        return "Your cart is empty. Search for products to add!"
                else:
                    return "Couldn't access your cart right now. Please try again."
            
            elif intent == 'recommendations':
                budget = self._extract_budget(user_message)
                result = await self.list_all_products()
                
                if result.get("status") == "success" and result.get("products"):
                    products = result["products"]
                    
                    # Apply budget filter if specified
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
                ml_status = "with semantic understanding" if self.semantic_engine.model else "with basic keyword matching"
                return f"""I'm your AI shopping assistant {ml_status}! Here's what I can do:

Search Products:
• "find wireless headphones"
• "search for blue dresses under $50"  
• "show me laptops"

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
• "show product details"

Just tell me what you need in natural language!"""
            
            else:
                return f"I understood you said: '{user_message}'\n\nI can help you search for products, manage your cart, or get recommendations. What would you like to do? Type 'help' for more options."
        
        except Exception as e:
            logger.error(f"Error processing request: {e}")
            return "Sorry, I had trouble processing that request. Please try again or type 'help' for assistance."
    
    def _extract_search_terms(self, message: str, intent: str) -> str:
        """Extract search terms from message"""
        terms_to_remove = [
            'search for', 'find', 'look for', 'show me', 'get me',
            'i need', 'i want', 'looking for', 'searching for',
            'where can i find', 'do you have'
        ]
        
        msg = message.lower()
        for term in terms_to_remove:
            msg = msg.replace(term, '')
        
        return msg.strip()
    
    def _extract_product_id(self, message: str) -> Optional[str]:
        """Extract product ID from message"""
        patterns = [
            r'(?:add|buy|purchase)\s+([A-Za-z0-9_-]+)',
            r'(?:id|product)\s*:?\s*([A-Za-z0-9_-]+)',
            r'`([A-Za-z0-9_-]+)`'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1)
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

# Initialize shopping agent
shopping_agent = ShoppingAgent()

@app.post("/chat")
async def chat_with_concierge(request: ConversationRequest):
    """Chat endpoint with optional semantic understanding"""
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
            "semantic_enhanced": shopping_agent.semantic_engine.model is not None
        }
    
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def search_products(request: ProductQuery):
    """Search endpoint with optional semantic capabilities"""
    enhanced = shopping_agent.semantic_engine.model is not None
    result = await shopping_agent.search_products(request.query, enhanced=enhanced)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message", "Search failed"))
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
            raise HTTPException(status_code=500, detail=result.get("message", "Action failed"))
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cart action error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/recommendations")
async def get_recommendations(request: ProductRecommendationRequest):
    try:
        result = await shopping_agent.list_all_products()
        
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message", "Recommendations failed"))
        
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    # Test MCP connection
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{MCP_SERVER_URL}/health")
            mcp_ok = response.status_code == 200
    except:
        mcp_ok = False
    
    # Check component status
    semantic_ok = shopping_agent.semantic_engine.model is not None
    spacy_ok = shopping_agent.semantic_engine.nlp is not None
    
    return {
        "status": "healthy",
        "service": "adk-agents",
        "version": "2.0.0",
        "mcp_server": "ok" if mcp_ok else "down",
        "semantic_search": "enabled" if semantic_ok else "disabled",
        "nlp_processor": "advanced" if spacy_ok else "basic",
        "ml_libraries": "available" if ML_AVAILABLE else "not available",
        "spacy": "available" if SPACY_AVAILABLE else "not available"
    }

@app.get("/")
async def root():
    ml_status = []
    if ML_AVAILABLE:
        ml_status.append("Semantic search")
    if SPACY_AVAILABLE:
        ml_status.append("Advanced NLP")
    if not ml_status:
        ml_status.append("Basic keyword matching")
    
    return {
        "service": "ADK Shopping Concierge",
        "version": "2.0.0", 
        "status": "running",
        "description": f"AI shopping assistant with {', '.join(ml_status).lower()}",
        "features": ml_status + [
            "Natural language understanding", 
            "Intent classification",
            "Product search and recommendations",
            "Cart management"
        ],
        "endpoints": [
            "/chat", "/search", "/cart/action", "/recommendations", "/health", "/docs"
        ]
    }