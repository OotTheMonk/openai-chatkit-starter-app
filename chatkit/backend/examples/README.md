# CardSearchWidget Examples

This directory contains practical examples of using the `CardSearchWidget` implementation.

## Files

### `widget_example.py`
Runnable examples demonstrating different usage patterns.

**Run it:**
```bash
cd chatkit/backend
python examples/widget_example.py

# Or search for a specific card:
python examples/widget_example.py "Luke Skywalker"
```

**Examples included:**
1. Basic search with results
2. Error handling
3. Widget state serialization
4. Manual fetch & control
5. Command-line search

### `widgets_api.py`
FastAPI integration showing how to add REST endpoints.

**How to use:**
```python
# In your main.py:
from examples.widgets_api import router

app.include_router(router)

# Then test:
# GET /api/cards/search?q=Luke
# POST /api/cards/search (with JSON body)
# GET /api/cards/search/Yoda
```

## Quick Test

### 1. Test Widget Directly
```bash
cd chatkit/backend
python -c "
import asyncio
from app.widgets import CardSearchWidget

async def test():
    widget = await CardSearchWidget.from_search('Luke Skywalker')
    print(f'Found {len(widget.results)} cards')
    if widget.results:
        print('First result:', widget.results[0])

asyncio.run(test())
"
```

### 2. Test in Chat
Start the backend and chat:
```
npm run dev
# Chat: "Find cards with Luke Skywalker"
# Assistant will use search_cards tool automatically
```

### 3. Test REST Endpoint (if added to main.py)
```bash
curl "http://127.0.0.1:8000/api/cards/search?q=Luke"
```

## Common Use Cases

### Use Case 1: Simple Card Search
```python
widget = await CardSearchWidget.from_search("Yoda")
print("\n".join(widget.results))
```

### Use Case 2: Build Response Message
```python
widget = await CardSearchWidget.from_search(user_query)
message = f"Found {len(widget.results)} cards:\n" + "\n".join(widget.results)
```

### Use Case 3: Export for Frontend
```python
widget = await CardSearchWidget.from_search(query)
state_dict = widget.to_dict()
# Send to frontend for custom rendering
```

### Use Case 4: REST Endpoint
```python
@app.get("/api/cards")
async def get_cards(q: str):
    widget = await CardSearchWidget.from_search(q)
    return widget.to_dict()
```

## Integration Checklist

- [x] Widget created and working
- [x] Tool integrated into agent
- [x] Examples provided
- [x] Documentation complete
- [ ] Custom REST endpoints added (optional)
- [ ] Frontend integration (optional)
- [ ] Caching implemented (optional)
- [ ] Database persistence (optional)

## Next Steps

1. **Test** - Run the examples to verify everything works
2. **Integrate** - Add REST endpoints if you need API access
3. **Extend** - Add caching, pagination, or other features
4. **Deploy** - Widget works as-is in production

## Troubleshooting

### Import Error
```
ModuleNotFoundError: No module named 'app.widgets'
```
Make sure you're running from the `chatkit/backend` directory.

### Search Timeout
The widget has a 10-second timeout for API requests. Check:
- Network connectivity
- API endpoint availability (`http://142.11.210.6/es/swucardsearch.php`)
- Firewall rules

### No Results
Some searches may legitimately return no results. Check the `error` field:
```python
widget = await CardSearchWidget.from_search(query)
if widget.error:
    print(f"Error: {widget.error}")
elif not widget.results:
    print("No cards found")
```

## See Also

- `WIDGET_DOCS.md` - Complete documentation
- `INTEGRATION_GUIDE.py` - Integration patterns
- `app/widgets.py` - Source code
- `app/server.py` - Agent configuration
