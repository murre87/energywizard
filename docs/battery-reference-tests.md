# Independent battery-plan reference

`tests/battery_reference.py` enumerates all supported action sequences for at most
six quarters (up to 15,625 candidates). It has no dependency on runtime planner
helpers and never controls devices. Its objective/physical equations are stated
in the module docstring and checked against hand-calculated examples.

The production planner quantizes stored energy; the reference integrates continuous
energy. Strict comparisons therefore use initial states, power, efficiencies and
limits that land on the selected grid. Tolerance is 1e-7 currency units on objective,
1e-5 kWh on energy and 0.00051 kW for rounded output power. These are numerical
rounding tolerances, not an allowance for economic regressions. General nonaligned
production scenarios need a separately justified discretization error bound before
being used for an optimality claim. This suite does not prove global optimality for
arbitrary installations or longer horizons.

Equivalent action schedules pass if they have equivalent feasible objective values.
Checks cover negative prices, reserves/ceilings, losses, cycle and stored-energy
wear, mode switching, physical reversals through idle, terminal energy, export
limits, supported actions and all three EV policies. Deliberately incorrect physics
and economically inferior schedules must fail the independent checker.
