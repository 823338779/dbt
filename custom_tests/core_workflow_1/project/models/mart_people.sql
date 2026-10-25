select id, upper(name) as name, registered_on from {{ ref('stg_people') }}
