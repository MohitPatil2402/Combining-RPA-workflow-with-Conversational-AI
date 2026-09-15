"""
Training data for Layer 1 (NLU).

This module is the single source of truth for intents, entities and training
phrases. Both consumers read from here, so the two engines always agree on
what the agent knows:

  * nlu/dialogflow_setup.py  - uploads these into a real Dialogflow ES agent
  * nlu/local_classifier.py  - trains the offline classifier from them

VALIDATION_PHRASES is a separately authored held-out set. It is deliberately
*not* a random split of TRAINING_PHRASES: the wordings differ, so measuring
against it says something real about generalisation rather than memorisation.
It also contains OUT_OF_SCOPE phrases, which the agent is supposed to be
unsure about - they are what makes the confidence threshold meaningful.
"""

# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

# Order IDs in the mock CRM live in the 45xx range.
ORDER_ID_PATTERN = r"\b(4[5-9]\d{2})\b"

# Appliance categories, with the synonyms customers actually type.
CATEGORY_ENTITY = {
    "Television": ["television", "tv", "led tv", "smart tv", "telly", "t.v."],
    "Washing Machine": [
        "washing machine", "washer", "washing m/c", "wm", "front load",
        "top load",
    ],
    "Mixer Grinder": [
        "mixer grinder", "mixer", "grinder", "mixie", "mixi", "juicer mixer",
    ],
    "Refrigerator": ["refrigerator", "fridge", "freezer", "double door"],
    "Air Conditioner": [
        "air conditioner", "ac", "a.c.", "split ac", "window ac", "aircon",
    ],
}

# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------
# required_entities drives multi-turn slot filling: when one is missing the
# orchestrator asks a follow-up question instead of failing the request.
INTENTS = {
    "order.status": {
        "display_name": "Order Status",
        "required_entities": ["order_id"],
        "automatable": True,
        "description": "Customer wants to know where their order is.",
    },
    "order.refund": {
        "display_name": "Refund Request",
        "required_entities": ["order_id"],
        "automatable": True,
        "description": "Customer wants their money back for an order.",
    },
    "order.address_update": {
        "display_name": "Address Update",
        # new_address is never present in the opening message in practice, so
        # this intent is the one that exercises multi-turn slot filling: the
        # orchestrator asks for the address and the customer's next message
        # supplies it.
        "required_entities": ["order_id", "new_address"],
        "automatable": True,
        "description": "Customer wants the delivery address changed.",
    },
    "order.complaint": {
        "display_name": "Complaint",
        "required_entities": [],
        "automatable": False,
        "description": "Product is faulty or the customer is unhappy. "
                       "Always handled by a person.",
    },
    "agent.escalation_request": {
        "display_name": "Escalation Request",
        "required_entities": [],
        "automatable": False,
        "description": "Customer explicitly asks for a human agent.",
    },
}

# ---------------------------------------------------------------------------
# Training phrases
# ---------------------------------------------------------------------------
# Typos, casual phrasing and Hindi-English code-mixing are intentional - they
# are what real customer chat logs look like, and leaving them out is how a
# demo agent ends up brittle on the day.
TRAINING_PHRASES = {
    "order.status": [
        "Where is my order 4521",
        "wheres my order 4521",
        "where is my order #4508",
        "track my order 4503",
        "can you track order 4511 for me",
        "what is the status of order 4515",
        "status of my order 4502",
        "order 4519 status please",
        "when will my order 4506 arrive",
        "when is my tv getting delivered",
        "delivery date for order 4510",
        "has my washing machine been shipped",
        "is my fridge dispatched yet",
        "my order 4504 has not arrived",
        "still waiting for order 4517",
        "order 4513 kab aayega",
        "mera order 4509 kaha hai",
        "kab tak milega order 4505",
        "any update on my order 4518",
        "update on order 4512 please",
        "did my mixer ship",
        "i want to know where my ac is",
        "checking on order 4507",
        "whats happening with order 4520",
        "order no 4514 current status",
        "plz tell me status of 4501",
        "shipment details for order 4516",
        "is order 4503 out for delivery",
        "my parcel 4511 hasnt come",
        "tracking info for my television order",
        "hi where is my washing machine order 4506",
        "order status 4502",
        "need delivery update for 4519",
        "my refrigerator order is late",
        "how many days for order 4515 to reach",
    ],
    "order.refund": [
        "I want a refund for order 4521",
        "refund my order 4508",
        "i want my money back for order 4508",
        "please refund order 4503",
        "can i get a refund on order 4511",
        "process refund for 4515",
        "i need refund of my order 4502",
        "want to return and get refund for order 4519",
        "refund chahiye order 4506 ka",
        "mujhe paisa wapas chahiye order 4510",
        "give me my money back for the tv",
        "cancel order 4504 and refund",
        "i am returning the mixer, refund please",
        "refund karo order 4517",
        "how do i get a refund for order 4513",
        "i want refund for my washing machine order 4509",
        "refund request for order 4505",
        "please return my payment for order 4518",
        "money back for order 4512",
        "initiate refund 4507",
        "refnd for order 4520",
        "i want to cancel and get refund 4514",
        "refund of 500 for order 4501",
        "refund 12000 for order 4516",
        "pls refund the amount for order 4503",
        "want my payment reversed for 4511",
        "the ac is returned, where is my refund",
        "start refund process for order 4506",
        "i would like a refund on my fridge order",
        "refund pending for order 4502",
        "need money back order 4519",
        "reimburse me for order 4515",
        "kindly refund order 4508 amount",
        "can u refund 4510 please",
    ],
    "order.address_update": [
        "change delivery address for order 4521",
        "i want to update the address on order 4508",
        "update my address for order 4503",
        "please change the shipping address for 4511",
        "can you deliver order 4515 to a different address",
        "wrong address on order 4502, please fix",
        "i moved, change address for order 4519",
        "address change for order 4506",
        "new address for my order 4510",
        "deliver order 4504 to my office instead",
        "address galat hai order 4517 ka",
        "mera address change karna hai order 4513",
        "i entered the wrong address for order 4509",
        "modify delivery address order 4505",
        "can i change where order 4518 is delivered",
        "shift delivery of order 4512 to another address",
        "update shipping details for 4507",
        "correct the address on order 4520",
        "change addres for order 4514",
        "i need to change my delivery location for 4501",
        "please send order 4516 to a new address",
        "edit address order 4503",
        "wrong pincode on my tv order, need to change",
        "change the address for my washing machine order 4511",
        "my address is incorrect for order 4506",
        "can you update address of order 4502",
        "delivery address needs changing for 4519",
        "want to redirect order 4515 elsewhere",
        "please change my house address for order 4510",
        "address update required order 4508",
    ],
    "order.complaint": [
        "my tv arrived broken",
        "the washing machine is not working",
        "received a damaged mixer grinder",
        "my fridge is making a loud noise",
        "the ac is not cooling at all",
        "product is defective",
        "this is the worst service ever",
        "i am very unhappy with my purchase",
        "the television screen is cracked",
        "my order arrived in a damaged box",
        "washing machine stopped working after 2 days",
        "mixer is faulty, it smells like burning",
        "very poor quality product",
        "the fridge door is dented",
        "ac installation was terrible",
        "i have a complaint about my order 4508",
        "want to file a complaint",
        "the product is not as described",
        "wrong item delivered",
        "i received a different model than i ordered",
        "tv kharab hai",
        "machine kaam nahi kar rahi",
        "bohot ghatiya product hai",
        "this is unacceptable service",
        "my appliance broke within a week",
        "damaged product received order 4515",
        "the item is completely useless",
        "disappointed with the quality",
        "my new ac leaks water",
        "grinder jar is cracked",
        "worst experience, product faulty",
        "the refrigerator is not cooling properly",
    ],
    "agent.escalation_request": [
        "i want to talk to a human",
        "connect me to an agent",
        "let me speak to a person",
        "transfer me to customer care",
        "i need to speak with someone",
        "get me a real person",
        "can i talk to your manager",
        "human agent please",
        "i dont want to talk to a bot",
        "put me through to support",
        "call me back please",
        "this bot is useless, get me an agent",
        "i want to escalate this",
        "escalate my case",
        "need to speak to a supervisor",
        "customer care se baat karni hai",
        "mujhe insaan se baat karni hai",
        "agent se connect karo",
        "give me the helpline number",
        "can someone call me",
        "i need real help not a chatbot",
        "speak to representative",
        "please connect to live agent",
        "raise this to your senior",
        "i demand to speak to a manager",
        "talk to human",
        "live chat with agent please",
        "forward this to a person",
    ],
}

# ---------------------------------------------------------------------------
# Held-out validation set (different wordings from the training phrases)
# ---------------------------------------------------------------------------
VALIDATION_PHRASES = {
    "order.status": [
        "could you check what happened to order 4507",
        "i placed order 4512 last week, any news",
        "delivery status 4504 pls",
        "hasnt my order 4518 shipped yet",
        "when does 4501 reach me",
        "whr is ordr 4509",
        "order 4514 ka kya hua",
        "looking for an update on my refrigerator delivery",
        "tell me if order 4520 is dispatched",
        "my smart tv order hasnt arrived, whats the status",
    ],
    "order.refund": [
        "how long until i get refunded for 4505",
        "i returned the item, please send my money back for order 4513",
        "want reimbursement for order 4516",
        "pls process my refund 4504",
        "get my payment back for 4518 please",
        "order 4501 refund kab milega",
        "id like to cancel and be refunded for my ac order 4520",
        "refund the full amount of order 4509",
        "can you reverse the charge on 4514",
        "money return karna hai order 4512",
    ],
    "order.address_update": [
        "need a different delivery address for 4504",
        "i typed my flat number wrong on order 4518",
        "can the courier deliver 4513 somewhere else",
        "please amend the address on order 4509",
        "changing my shipping address for 4520",
        "order 4501 ka address badalna hai",
        "i want my mixer delivered to another house",
        "fix the delivery address for 4516",
        "relocate delivery of order 4505",
        "my street name is wrong on order 4514",
    ],
    "order.complaint": [
        "the appliance i got is broken beyond use",
        "terrible product, it failed immediately",
        "my washing machine drum is making noise",
        "got a scratched refrigerator",
        "the tv i received does not switch on",
        "product bilkul kharab nikla",
        "im furious about the condition of my order",
        "defective unit delivered again",
        "the air conditioner smells burnt",
        "quality is horrible, very upset",
    ],
    "agent.escalation_request": [
        "please get me someone who can actually help",
        "i would rather speak with a human being",
        "route me to an executive",
        "can a person call me about this",
        "i need a live representative now",
        "bot nahi chahiye, agent chahiye",
        "hand this over to your team lead",
        "i want to be transferred to support staff",
        "let me chat with an actual employee",
        "escalate to a senior please",
    ],
}

# Phrases the agent has no intent for. A well-tuned threshold keeps these
# below the automation line so they escalate instead of being guessed at.
OUT_OF_SCOPE_PHRASES = [
    "something's wrong with my stuff",
    "hello",
    "hi there",
    "what are your working hours",
    "do you sell laptops",
    "thanks a lot",
    "ok",
    "help",
    "i have an issue",
    "can you help me",
    "whats going on",
    "hmm not sure",
    "is anyone there",
    "good morning",
    "what do you do",
]


def all_intent_names():
    return list(INTENTS.keys())


def training_pairs():
    """Yield (text, intent_name) for every training phrase."""
    for intent, phrases in TRAINING_PHRASES.items():
        for phrase in phrases:
            yield phrase, intent


def validation_pairs():
    """Yield (text, intent_name) for the held-out set.

    Out-of-scope phrases are yielded with an intent of None - the correct
    behaviour for those is "not confident enough to automate".
    """
    for intent, phrases in VALIDATION_PHRASES.items():
        for phrase in phrases:
            yield phrase, intent
    for phrase in OUT_OF_SCOPE_PHRASES:
        yield phrase, None
