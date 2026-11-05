# Entity Loader Plugin

The Entity Loader plugin (`entloader.py`) loads `.ent` files and replaces map entities by copying the .ent file to match the current map name, then restarting the map. The Quake Live engine automatically loads `mapname.ent` files when they exist alongside `mapname.bsp`.

## How It Works

1. You create custom `.ent` files with entity definitions
2. Place them in your server's maps directory (`fs_homepath/baseq3/maps/`)
3. Use `!eload` to copy your custom .ent to match the current map
4. The map restarts and loads with your custom entities
5. Use `!eclear` to remove the custom .ent and restore BSP entities

## Installation

1. Copy `entloader.py` to your minqlx plugins directory
2. By default, the plugin looks for `.ent` files in `fs_homepath/baseq3/maps/` (the server's map directory)
   - Place your `.ent` files in the same directory as your `.bsp` map files
3. The plugin will be active after server restart or `!reload entloader`

## Quick Start

```
!elist                     # List available .ent files
!eload dividedcrossings    # Load dividedcrossings.ent for current map
!einfo dividedcrossings    # Show entity info
!eclear                    # Remove custom entities and restore BSP entities
```

## .ent File Format

`.ent` files use the standard Quake entity format. Each entity is defined in a block with key-value pairs:

```
{
"classname" "item_armor_body"
"origin" "100 200 50"
"angle" "0"
}
{
"classname" "weapon_rg"
"origin" "500 600 150"
"angle" "180"
}
```

**IMPORTANT:** Your `.ent` file must contain ALL entities you want on the map, since all BSP entities will be removed when you load the file. This includes:
- Item spawns (armor, health)
- Weapon spawns
- Ammo spawns
- Power-up spawns
- Any other map entities you need

### Common Entity Properties

- **classname**: The type of entity (required)
  - Items: `item_armor_body`, `item_armor_shard`, `item_health_small`, `item_health_large`, `item_health_mega`
  - Weapons: `weapon_rg`, `weapon_sg`, `weapon_rl`, `weapon_lg`, `weapon_pg`, `weapon_cg`, `weapon_gl`, `weapon_bfg`
  - Ammo: `ammo_cells`, `ammo_rockets`, `ammo_slugs`, `ammo_belt`
  - Power-ups: `holdable_quad`, `holdable_haste`, `holdable_invisibility`, etc.

- **origin**: Position in the map as "X Y Z" coordinates (space-separated)

- **angle**: Rotation angle in degrees (0, 45, 90, 135, 180, 225, 270, 315)

- **count**: Number of items to spawn (for ammo and health items)

### Example Entity Files

#### Standard Deathmatch Setup
```
{
"classname" "item_armor_body"
"origin" "0 0 0"
"angle" "0"
}
{
"classname" "weapon_rg"
"origin" "256 256 32"
"angle" "90"
}
{
"classname" "ammo_cells"
"origin" "512 512 64"
"angle" "180"
}
```

#### Quad Arena
```
{
"classname" "holdable_quad"
"origin" "1024 1024 128"
"angle" "0"
}
{
"classname" "item_health_mega"
"origin" "1024 1100 64"
"angle" "90"
}
```

## Commands

### !eload <filename>
Load entities from a .ent file by copying it to match the current map name and restarting the map.

**Usage:** `!eload dividedcrossings` or `!eload dividedcrossings.ent`

**Example:**
```
!eload dividedcrossings
> Copied 'dividedcrossings.ent' to 'campgrounds.ent'.
> Contains 45 entities. Restarting map to apply...
```

### !elist
List all available .ent files in the entity directory.

**Example:**
```
!elist
> Available entity files: dividedcrossings, campgrounds, bloodrun
```

### !einfo <filename>
Show entity count and entity types in a .ent file without loading it.

**Usage:** `!einfo dividedcrossings`

**Example:**
```
!einfo dividedcrossings
> File 'dividedcrossings.ent' contains 45 entities:
>   weapon_rocketlauncher: 4
>   weapon_railgun: 2
>   item_armor_body: 3
>   item_health_mega: 2
```

### !eclear
Remove the current map's .ent file and restart with BSP entities.

**Example:**
```
!eclear
> Removed 'campgrounds.ent'. Restarting map to restore BSP entities...
```

### !etest
Test command to verify plugin is working and show loaded .ent files.

**Example:**
```
!etest
> Entity Loader plugin is working!
> Entity directory: /home/qlserver/.quakelive/baseq3/maps
> Files found: 3
>   - dividedcrossings.ent
>   - campgrounds.ent
>   - bloodrun.ent
```

## Configuration CVars

### qlx_entUseBasePath
Whether to use the server's home path (`fs_homepath/baseq3/maps/`) for entity files. When enabled, `.ent` files are loaded from the same directory as your `.bsp` map files.

**Default:** `1` (enabled)

**Behavior:**
- When enabled: Looks for `.ent` files in `fs_homepath/baseq3/maps/` (same location as `.bsp` files)
- When disabled: Uses the path specified by `qlx_entDirectory`

**Example:**
```
qlx_entUseBasePath 0  # Disable and use qlx_entDirectory instead
```

### qlx_entDirectory
Path to the directory containing .ent files. Only used if `qlx_entUseBasePath` is disabled. Can be absolute or relative.

**Default:** `ent`

**Example:**
```
qlx_entDirectory "/path/to/entities"
qlx_entUseBasePath 0  # Must also disable basepath usage
```

### qlx_entAutoLoad
Automatically load entity files matching the current map name when the map changes. This will replace all BSP entities with your custom layout.

**Default:** `1` (enabled)

**Behavior:**
- When enabled and map `asylum` loads, the plugin tries to load `asylum.ent`
- If found, ALL BSP entities are replaced with entities from `asylum.ent`
- If not found, nothing happens (no error, map uses original BSP entities)
- Your `asylum.ent` file must contain all entities for the map

**Example:**
```
qlx_entAutoLoad 0  # Disable auto-load
```

## Workflow Examples

### Custom Complete Map Setup (Default - Using fs_basepath)
1. Export entities from your map (e.g., using Radiant or a map editor)
2. Save them to `mymap.ent`
3. Place the `.ent` file in your server's map directory (same location as `mymap.bsp`)
   - This is typically `fs_basepath/baseq3/maps/mymap.ent`
4. When the map `mymap` is loaded with auto-load enabled, all BSP entities are replaced with your custom layout
5. Or manually use `!entload mymap`

### Alternative: Custom Entity Directory
1. Set `qlx_entUseBasePath 0` in your server config
2. Create an `ent/` directory or point to another directory with `qlx_entDirectory`
3. Place your `.ent` files there
4. Use `!entload filename` to load entities from your custom directory

### Experimenting with Different Layouts
1. Create multiple `.ent` files (complete entity sets) in your maps directory:
   - `layout1.ent` - One complete entity set
   - `layout2.ent` - Different complete entity set
   - `layout3.ent` - Another complete entity set
2. Use `!entload layout1`, `!entload layout2` to switch between them
3. Each load will replace ALL entities with the complete set from the file

### Creating Balanced Weapon Layouts
1. Create `weapons_balanced.ent` with a complete, balanced entity set
2. Create `weapons_heavy.ent` with more powerful weapons and less health
3. Create `weapons_light.ent` with more health and fewer weapons
4. Place all files in your map directory
5. Switch using `!entload weapons_balanced`, `!entload weapons_heavy`, etc.

All files must be complete entity definitions.

## Notes

- **Entity Replacement:** Loading a .ent file removes ALL existing map entities and replaces them with only the entities in the file
- Your .ent files must be complete with all entities you want (items, weapons, spawns, etc.)
- Entity changes take effect immediately on the server
- Use `!entclear` to remove all loaded custom entities
- The plugin uses the minqlx framework for integration
- Comments in .ent files (lines starting with //) are automatically ignored
- Both quoted and unquoted key-value formats are supported
- The `auto-load` feature requires the .ent file name to match the map name exactly

## Troubleshooting

**No .ent files found**
- Verify the `qlx_entDirectory` cvar points to the correct directory
- Make sure .ent files are in the correct location
- Use `!entlist` to verify files are discoverable

**Entities not appearing or map seems empty**
- Verify your .ent file contains ALL entities needed (items, weapons, health, spawns)
- Remember that loading a .ent file removes ALL existing BSP entities
- Check that the .ent file format is correct (proper braces and quoted keys/values)
- Use `!entinfo` to verify entities were parsed correctly
- Check the server log for spawn errors

**Auto-load not working**
- Verify `qlx_entAutoLoad` is set to `1`
- Ensure the .ent file name matches the map name exactly (case-sensitive)
- Check server logs for auto-load attempts
- Verify the file contains a complete entity set

**Missing items/weapons after load**
- Your .ent file may be incomplete
- Make sure you included all items, weapons, ammo, and spawns
- Use `!entinfo` to see what entities are in your file
- Compare with the original map's entity count

**Unexpected map behavior**
- If items don't respawn properly, check your entity definitions
- Ensure all spawn points and entities have valid origins
- Check for duplicate entities or overlapping spawns
