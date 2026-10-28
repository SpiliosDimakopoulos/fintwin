# CR (code-review fixes) requests to other workstreams

## To B1 (`tests/test_B1_calibration.py`): two assertions encode the old trailing window (CR-4)

CR-4 makes the calibration's trailing windows (TTM revenue, 4/8-quarter ratios, the covenant history `ebit_ttm0`,
`ebitda_ttm0`, `interest_ttm0`) contiguous. `_new_layer` puts the gap row 3 rows back, so the last 4 *reported* rows
span a hole; the run that ends at the cutoff is now the last 2 quarters, and the 2 earlier slots of the covenant
history take the run's average. Replace, in `test_data_layer_gaps_and_missing_last_values_give_finite_params`:

```python
    rep = q[~q["gap"]].tail(4)
    assert p["ebit_ttm0"] == pytest.approx(rep["operating_income"].tolist())  # no zero quarter from the gap row
```

with

```python
    x = q["operating_income"].tail(2).to_numpy()  # the 2-quarter run after the gap row, earlier slots at its mean
    assert p["ebit_ttm0"] == pytest.approx([x.mean(), x.mean(), *x])  # no zero quarter from the gap row (CR-4)
    assert "x 4/2" in p["_sources"]["trailing"]
```

and, in `test_F4_uses_the_fiscal_year_da_when_quarterly_da_is_missing`:

```python
    rep = q[~q["gap"]].tail(4)
    assert p["ebitda_ttm0"] == pytest.approx((rep["operating_income"] + rep["da_annual"]).tolist())
```

with

```python
    x = (q["operating_income"] + q["da_annual"]).tail(2).to_numpy()
    assert p["ebitda_ttm0"] == pytest.approx([x.mean(), x.mean(), *x])
```

Firms whose last 8 quarters are consecutive (every firm that passes `contiguous(q, 16)`) are unchanged; the B1 parity
goldens pass.
