<?xml version="1.0" encoding="UTF-8"?>
<graph name="load_orders">
  <node name="read_raw" type="Input Table"><parameter name="table">raw.orders</parameter></node>
  <node name="write_stg" type="Output Table"><parameter name="table">stg.orders_clean</parameter></node>
  <flow from="read_raw" to="write_stg"/>
</graph>
