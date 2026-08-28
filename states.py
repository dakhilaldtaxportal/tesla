from aiogram.fsm.state import State, StatesGroup

class AdminStates(StatesGroup):
    waiting_vendor_location = State()

class VendorStates(StatesGroup):
    waiting_delivery_text = State()
    waiting_broadcast_text = State()

class RiderStates(StatesGroup):
    waiting_location = State()
