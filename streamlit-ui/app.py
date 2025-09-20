import streamlit as st
import httpx
import json
import time

st.set_page_config(
    page_title="AI Shopping Concierge",
    page_icon="🛍️",
    layout="wide"
)

# URLs for the other services in the cluster
ADK_AGENTS_URL = "http://adk-agents-service.default.svc.cluster.local:8000"
MCP_SERVER_URL = "http://mcp-server-service.default.svc.cluster.local:8080"

# Set up session state stuff
if 'user_id' not in st.session_state:
    # Use the same hardcoded session ID as the frontend when ENABLE_SINGLE_SHARED_SESSION=true
    # This ensures cart synchronization between AI agent and web frontend
    st.session_state.user_id = "12345678-1234-1234-1234-123456789123"
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'cart_items' not in st.session_state:
    st.session_state.cart_items = []
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'last_search_query' not in st.session_state:
    st.session_state.last_search_query = ""
if 'last_cart_refresh' not in st.session_state:
    st.session_state.last_cart_refresh = 0

def make_request(url: str, method: str = "GET", data: dict = None, timeout: float = 30.0):
    try:
        with httpx.Client(timeout=timeout) as client:
            if method == "GET":
                response = client.get(url)
            else:
                response = client.post(url, json=data)
            
            response.raise_for_status()
            return response.json()
            
    except httpx.TimeoutException:
        error_msg = f"Request timed out after {timeout} seconds"
        st.error(error_msg)
        return {"status": "error", "message": error_msg}
    except httpx.ConnectError:
        error_msg = "Connection failed - service may be down"
        st.error(error_msg)
        return {"status": "error", "message": error_msg}
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
        st.error(error_msg)
        return {"status": "error", "message": error_msg}
    except Exception as e:
        error_msg = f"Request failed: {str(e)}"
        st.error(error_msg)
        return {"status": "error", "message": error_msg}

def chat_with_agent(message: str, user_id: str) -> str:
    data = {
        "messages": [{"role": "user", "content": message}],
        "user_id": user_id
    }
    
    result = make_request(f"{ADK_AGENTS_URL}/chat", "POST", data)
    
    if result.get("status") == "success":
        return result.get("response", "Sorry, couldn't process that.")
    else:
        return f"Error: {result.get('message', 'Unknown error')}"

def search_products(query: str):
    data = {"query": query}
    return make_request(f"{MCP_SERVER_URL}/search_products", "POST", data)

def get_cart_contents(user_id: str):
    data = {"user_id": user_id}
    return make_request(f"{MCP_SERVER_URL}/get_cart_contents", "POST", data)

def add_to_cart(user_id: str, product_id: str, quantity: int = 1):
    data = {
        "user_id": user_id,
        "product_id": product_id,
        "quantity": quantity
    }
    return make_request(f"{MCP_SERVER_URL}/add_item_to_cart", "POST", data)

def remove_from_cart(user_id: str, product_id: str):
    data = {
        "user_id": user_id,
        "product_id": product_id
    }
    return make_request(f"{MCP_SERVER_URL}/remove_item_from_cart", "POST", data)

def get_product_details(product_id: str):
    data = {"product_id": product_id}
    return make_request(f"{MCP_SERVER_URL}/get_product_details", "POST", data)

def detect_cart_change(response_text: str) -> bool:
    """Detect if chat response indicates a cart change"""
    cart_change_indicators = [
        "added to cart", "added to your cart", "✅ added", "I've added",
        "removed from cart", "removed from your cart", "cart cleared"
    ]
    response_lower = response_text.lower()
    return any(indicator in response_lower for indicator in cart_change_indicators)

def format_price(price_dict):
    if not price_dict:
        return "Price N/A"
    
    units = price_dict.get("units", 0)
    nanos = price_dict.get("nanos", 0)
    
    return f"${units}.{nanos//10000000:02d}"

# main UI
st.title("🛍️ AI Shopping Concierge")
st.markdown("*GKE Hackathon Demo - ADK + MCP + Streamlit*")

# sidebar
st.sidebar.header("User Info")
# Display a friendlier session ID while keeping the actual shared session working
display_id = st.session_state.user_id
if display_id == "12345678-1234-1234-1234-123456789123":
    display_id = "Shared Session (Demo Mode)"
st.sidebar.write(f"Session: `{display_id}`")

# service status
st.sidebar.header("Services")
with st.sidebar:
    if st.button("Check Status"):
        adk_status = make_request(f"{ADK_AGENTS_URL}/health")
        mcp_status = make_request(f"{MCP_SERVER_URL}/health")
        
        if adk_status.get("status") == "healthy":
            st.success("🟢 ADK Agents OK")
        else:
            st.error("🔴 ADK Agents Down")
            
        if mcp_status.get("status") == "healthy":
            st.success("🟢 MCP Server OK")
        else:
            st.error("🔴 MCP Server Down")

# tabs
tab1, tab2, tab3, tab4 = st.tabs(["💬 Chat", "🔍 Search", "🛒 Cart", "📊 Stats"])

with tab1:
    st.header("Chat Assistant")
    
    # chat history display
    chat_container = st.container()
    
    with chat_container:
        for i, (role, message) in enumerate(st.session_state.chat_history):
            if role == "user":
                st.chat_message("user").write(message)
            else:
                st.chat_message("assistant").write(message)
    
    # chat input
    if prompt := st.chat_input("Ask about products, cart, etc..."):
        st.session_state.chat_history.append(("user", prompt))
        
        with st.spinner("Processing..."):
            response = chat_with_agent(prompt, st.session_state.user_id)
        
        st.session_state.chat_history.append(("assistant", response))
        
        # If chat response indicates cart changed, mark for refresh
        if detect_cart_change(response):
            st.session_state.last_cart_refresh = time.time()
            st.success("Cart updated! Check the 🛒 Cart tab to see changes.")
        
        st.rerun()
    
    if st.button("Clear Chat"):
        st.session_state.chat_history = []
        st.rerun()

with tab2:
    st.header("Product Search")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        search_query = st.text_input("Search products:", placeholder="shirts, electronics, etc...")
    
    with col2:
        search_btn = st.button("Search", type="primary")
    
    # Perform search and store results in session state
    if search_btn and search_query:
        if len(search_query.strip()) < 2:
            st.error("Search query must be at least 2 characters long")
        else:
            with st.spinner("Searching..."):
                results = search_products(search_query.strip())
            
            if results.get("status") == "success":
                # Store search results in session state
                st.session_state.search_results = results.get("results", [])
                st.session_state.last_search_query = search_query.strip()
            else:
                st.error("Search failed")
                st.session_state.search_results = []
    
    # Display search results from session state (persists across reruns)
    if st.session_state.search_results:
        products = st.session_state.search_results
        st.success(f"Found {len(products)} products matching '{st.session_state.last_search_query}'")
        
        cols = st.columns(3)
        for i, product in enumerate(products):
            with cols[i % 3]:
                st.subheader(product.get("name", "Unknown"))
                st.write(f"**Price:** {format_price(product.get('price', {}))}")
                st.write(f"**ID:** `{product.get('id', '')}`")
                
                desc = product.get("description", "")
                if desc:
                    st.write(f"**Desc:** {desc[:100]}{'...' if len(desc) > 100 else ''}")
                
                cats = product.get("categories", [])
                if cats:
                    st.write(f"**Categories:** {', '.join(cats)}")
                
                # Add to cart button - now this will persist across reruns!
                if st.button(f"Add to Cart", key=f"add_{product.get('id', i)}"):
                    result = add_to_cart(st.session_state.user_id, product.get('id', ''))
                    if result.get("status") == "success":
                        st.success("Added to cart!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"Add failed: {result.get('message', 'Unknown error')}")
                
                st.divider()
    
    elif st.session_state.last_search_query:
        st.info(f"No products found for '{st.session_state.last_search_query}'. Try different keywords.")

with tab3:
    st.header("Shopping Cart")
    
    # Show notification if cart was recently updated via chat
    if st.session_state.last_cart_refresh > 0 and (time.time() - st.session_state.last_cart_refresh) < 30:
        st.info("🔄 Cart was recently updated via chat! The cart contents below are current.")
        # Auto-refresh the cart display when we detect changes
        if st.button("🔄 Acknowledge Cart Update", type="primary"):
            st.session_state.last_cart_refresh = 0  # Clear the notification
            st.rerun()
    
    if st.button("Refresh Cart"):
        st.rerun()
    
    cart_result = get_cart_contents(st.session_state.user_id)
    
    if cart_result.get("status") == "success":
        items = cart_result.get("items", [])
        
        if items:
            st.success(f"{len(items)} items in cart")
            
            total_price = 0
            total_items = 0
            
            for item in items:
                product_id = item.get("product_id", "")
                quantity = item.get("quantity", 1)
                
                # get product details
                product_details = get_product_details(product_id)
                
                if product_details.get("status") == "success":
                    product = product_details.get("product", {})
                    price_dict = product.get('price', {})
                    
                    # Calculate item price
                    units = price_dict.get("units", 0)
                    nanos = price_dict.get("nanos", 0)
                    item_price = float(units) + float(nanos) / 1000000000
                    item_total = item_price * quantity
                    total_price += item_total
                    total_items += quantity
                    
                    col1, col2, col3 = st.columns([2, 1, 1])
                    
                    with col1:
                        st.write(f"**{product.get('name', 'Unknown Product')}**")
                        st.write(f"ID: `{product_id}`")
                        
                    with col2:
                        st.write(f"Qty: {quantity}")
                        st.write(f"Unit: {format_price(price_dict)}")
                        st.write(f"Total: ${item_total:.2f}")
                    
                    with col3:
                        st.write("**Actions**")
                        
                        # Quantity controls
                        col3a, col3b = st.columns(2)
                        with col3a:
                            if st.button("➖", key=f"dec_{product_id}"):
                                if quantity > 1:
                                    # Remove one
                                    remove_result = remove_from_cart(st.session_state.user_id, product_id)
                                    if remove_result.get("status") == "success":
                                        # Re-add with reduced quantity
                                        add_result = add_to_cart(st.session_state.user_id, product_id, quantity - 1)
                                        if add_result.get("status") == "success":
                                            st.rerun()
                                else:
                                    # Remove entirely
                                    remove_result = remove_from_cart(st.session_state.user_id, product_id)
                                    if remove_result.get("status") == "success":
                                        st.rerun()
                        
                        with col3b:
                            if st.button("➕", key=f"inc_{product_id}"):
                                remove_result = remove_from_cart(st.session_state.user_id, product_id)
                                if remove_result.get("status") == "success":
                                    add_result = add_to_cart(st.session_state.user_id, product_id, quantity + 1)
                                    if add_result.get("status") == "success":
                                        st.rerun()
                        
                        # Remove button
                        if st.button("🗑️ Remove", key=f"remove_{product_id}", type="secondary"):
                            remove_result = remove_from_cart(st.session_state.user_id, product_id)
                            if remove_result.get("status") == "success":
                                st.success("Item removed!")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(f"Remove failed: {remove_result.get('message', 'Unknown error')}")
                    
                    st.divider()
                else:
                    st.write(f"Product: {product_id} (details unavailable)")
            
            # Show totals
            if total_price > 0:
                st.markdown("---")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Total Items", total_items)
                
                with col2:
                    st.metric("Subtotal", f"${total_price:.2f}")
                
                with col3:
                    # Estimated tax (just for demo)
                    tax = total_price * 0.08  
                    st.metric("Est. Total", f"${total_price + tax:.2f}")
            
            # clear cart
            if st.button("Clear Cart", type="secondary"):
                clear_result = make_request(
                    f"{MCP_SERVER_URL}/empty_cart", 
                    "POST", 
                    {"user_id": st.session_state.user_id}
                )
                if clear_result.get("status") == "success":
                    st.success("Cart cleared successfully!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"Clear failed: {clear_result.get('message', 'Unknown error')}")
        else:
            st.info("Cart is empty - start shopping!")
    else:
        st.error("Can't load cart")

with tab4:
    st.header("Shopping Analytics")
    
    cart_result = get_cart_contents(st.session_state.user_id)
    
    if cart_result.get("status") == "success":
        items = cart_result.get("items", [])
        
        # Calculate real metrics
        total_value = 0
        total_qty = 0
        categories = {}
        
        for item in items:
            qty = item.get("quantity", 1)
            total_qty += qty
            
            # Get product details for pricing and categories
            product_details = get_product_details(item.get("product_id", ""))
            if product_details.get("status") == "success":
                product = product_details.get("product", {})
                price_dict = product.get('price', {})
                
                # Calculate value
                units = price_dict.get("units", 0)
                nanos = price_dict.get("nanos", 0)
                item_price = float(units) + float(nanos) / 1000000000
                total_value += item_price * qty
                
                # Count categories
                product_cats = product.get("categories", [])
                for cat in product_cats:
                    categories[cat] = categories.get(cat, 0) + qty
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Unique Items", len(items))
        
        with col2:
            st.metric("Total Quantity", total_qty)
        
        with col3:
            st.metric("Cart Value", f"${total_value:.2f}")
        
        with col4:
            avg_price = total_value / total_qty if total_qty > 0 else 0
            st.metric("Avg Item Price", f"${avg_price:.2f}")
        
        # Show category breakdown if available
        if categories:
            st.subheader("Items by Category")
            category_df = {
                "Category": list(categories.keys()),
                "Quantity": list(categories.values())
            }
            st.bar_chart(category_df, x="Category", y="Quantity")
        
        # Shopping session info
        st.subheader("Session Info")
        col1, col2 = st.columns(2)
        
        with col1:
            display_id = st.session_state.user_id
            if display_id == "12345678-1234-1234-1234-123456789123":
                display_id = "Shared Session (Demo Mode)"
            st.info(f"Session: `{display_id}`")
        
        with col2:
            st.info(f"Items in Cart: {len(items)} unique products")
    
    else:
        st.warning("Unable to load cart analytics")
        
        # Show placeholder analytics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Items", 0)
        with col2:
            st.metric("Total Value", "$0.00")
        with col3:
            st.metric("Categories", 0)

# footer
st.markdown("---")
st.markdown("**GKE Hackathon** | Streamlit + FastAPI + gRPC")