from dotenv import load_dotenv
from mem0 import MemoryClient
import logging
import json

load_dotenv()

user_name = "Ma'am"
mem0 = MemoryClient()

def add_memory():
    messages_formatted = [
        {
            "role": "user",
            "content": "I really like Jill Scott."
        },
        {
            "role": "assistant",
            "content": "That is a good choice."
        },
        {
            "role": "user",
            "content": "I think so too."
        },
        {
            "role": "assistant",
            "content": "What is your favorite song by them?"
        }
    ]

    mem0.add(messages_formatted, user_id="Ma'am")


def get_memory_by_query():
    mem0 = MemoryClient()

    query = f"What are {user_name}'s preferences?"
    results = mem0.search(
        query=query,
        filters={"user_id": user_name}
    )

    # Debug: Print the raw results to see the structure
    print("Raw results:")
    print(type(results))
    print(results)
    
    # If results is a dict with a 'results' key, access it
    if isinstance(results, dict) and 'results' in results:
        results = results['results']
    
    # Now process the results
    memories = []
    for result in results:
        print(f"\nResult type: {type(result)}")
        print(f"Result content: {result}")
        
        # Handle if result is a dict
        if isinstance(result, dict):
            memories.append({
                "memory": result.get("memory", result.get("text", str(result))),
                "updated_at": result.get("updated_at", "")
            })
        # Handle if result is a string
        else:
            memories.append({
                "memory": str(result),
                "updated_at": ""
            })

    memories_str = json.dumps(memories, indent=2)
    print(f"\nFormatted Memories:\n{memories_str}")
    return memories_str


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    add_memory()
    get_memory_by_query()