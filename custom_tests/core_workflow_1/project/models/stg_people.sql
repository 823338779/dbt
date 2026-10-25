select id, name, cast(registered_on as date) as registered_on from {{ ref('people') }}
