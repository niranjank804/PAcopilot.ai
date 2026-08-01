# Reference answer — paw_fixed_width_load

Held as a fixture so `evals/checks.py` can be unit-tested without calling a
provider. It is a *shape* reference: it must pass every deterministic check
in `paw_fixed_width_load.yaml`. It is not an authority on PAW behaviour.

Every function used below resolves in `src/tm1/functions` as TI-valid on
both v11 and v12.

---

PAW Modeler's datasource editor does not offer the fixed-width option you
would reach for in Architect, so `PositionDelimited` is not the route here
— it is an Architect-era choice, and a process authored around it is
awkward to maintain from Modeler. Instead, read the file as
`CharacterDelimited` with a delimiter that does not occur in the data, so
each record arrives whole in `v1`, then slice the columns yourself with
`SUBST()`.

That is the whole difference: Architect lets the datasource do the
column-splitting, whereas in PAW you take the line intact and split it in
the Data tab. The parsing moves from configuration into code, which is why
the two look different even though the file is the same.

**Prolog**

```tm1
# Read each line whole: the delimiter is chosen so it cannot occur in the
# source, which makes v1 the entire record.
DatasourceType = 'CHARACTERDELIMITED';
DatasourceNameForServer = pSourceFile;
DatasourceASCIIDelimiter = Char(1);
DatasourceASCIIQuoteCharacter = '';
DatasourceASCIIHeaderRecords = pHeaderRows;

nLoaded = 0;
nSkipped = 0;
```

**Data**

```tm1
# Column layout — replace the start and length of each field with the
# positions from your own file specification.
sAccount = TRIM( SUBST( v1, 1, 10 ) );
sCentre  = TRIM( SUBST( v1, 11, 8 ) );
sPeriod  = TRIM( SUBST( v1, 19, 6 ) );
sAmount  = TRIM( SUBST( v1, 25, 15 ) );

# A short final line means the layout does not match the file.
IF( LONG( v1 ) < 39 );
  nSkipped = nSkipped + 1;
  ItemReject( 'Record shorter than the declared layout.' );
ENDIF;

IF( DIMIX( '<YourAccountDimension>', sAccount ) = 0 );
  nSkipped = nSkipped + 1;
  ItemSkip;
ENDIF;

nAmount = StringToNumber( sAmount );

CellPutN( nAmount, '<YourCube>', sPeriod, sCentre, sAccount );
nLoaded = nLoaded + 1;
```

**Epilog**

```tm1
LogOutput( 'INFO', 'Loaded ' | NumberToString( nLoaded )
  | ' records, skipped ' | NumberToString( nSkipped ) | '.' );
```

**What you must supply**

- `<YourCube>` and `<YourAccountDimension>` — this process cannot know them.
- The start position and length of every field, from your file layout. The
  values above are placeholders, not a guess at your format.
- `pSourceFile` and `pHeaderRows` as process parameters.

Declare `v1` as a single String variable on the Variables tab — with the
delimiter set to a character absent from the data, it holds the full line.
