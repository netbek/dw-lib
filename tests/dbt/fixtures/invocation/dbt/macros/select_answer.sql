{% macro select_answer() %}
    {% set answer = var('answer') %}

    {% if answer != 42 %}
        {{ exceptions.raise_compiler_error("expected var 'answer' to be 42, got: " ~ answer) }}
    {% endif %}

    {% set query %}
        select {{ answer }} as answer
    {% endset %}

    {% set results = run_query(query) %}

    {# If we are in interactive mode (dbt run-operation), print the result to the console #}
    {% if execute %}
        {% do results.print_table() %}
        {{ return(results) }}
    {% endif %}
{% endmacro %}
