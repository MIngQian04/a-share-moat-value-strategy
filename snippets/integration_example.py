# Integration example for scripts/run_cycle_base_sequence_cppi.py
# This is a guide snippet, not a standalone script.

from brake.sell_side_brake import (
    SellSideBrakeInput,
    evaluate_sell_side_brake,
    apply_brake_cap,
)

# Add this state variable near your other position state variables:
trend_armed = False

# Reset it when entering a new theme/base position:
trend_armed = False

# Inside each trading-day loop, after original CPPI / step-add target exposure is computed:
x = SellSideBrakeInput(
    close=float(current_price),
    ma5=float(ma5),
    ma20=float(ma20),
    ma40=float(ma40),
    amount_ratio_5_20=float(amount_ratio_5_20),
    ret5=float(ret5),
)

brake = evaluate_sell_side_brake(x, trend_armed_prev=trend_armed)
trend_armed = brake.trend_armed

old_weight = cycle_weight
cycle_weight = apply_brake_cap(cycle_weight, brake.brake_cap)

if cycle_weight < old_weight:
    trades.append({
        "trade_date": date,
        "action": "SELL_SIDE_BRAKE",
        "theme": current_theme,
        "brake_state": brake.brake_state,
        "brake_reason": brake.brake_reason,
        "old_weight": old_weight,
        "new_weight": cycle_weight,
        "brake_cap": brake.brake_cap,
        "current_price": current_price,
        "ma5": ma5,
        "ma20": ma20,
        "ma40": ma40,
        "ma_spread": brake.ma_spread,
        "distribution_warning": brake.distribution_warning,
    })
